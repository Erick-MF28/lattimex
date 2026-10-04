// senda_core.cpp — SENDA, núcleo de ruteo en C++ del motor LATTIMEX.
//
// SENDA (Single-trajectory ENgine with Destroy-and-repair Adaptive search) sigue una sola
// trayectoria de búsqueda por corrida, sin población ni cruce:
//  1. INFACTIBILIDAD PENALIZADA: la búsqueda local y el ALNS trabajan con el objetivo
//     distancia + penalización * exceso de carga. La penalización se adapta en línea hacia una
//     fracción objetivo de candidatos factibles; la mejor solución *factible* se guarda aparte y
//     hay una reparación con 10x la penalización.
//  2. MOVIMIENTOS DE SEGMENTO (opcional): relocate-2 (Or-opt de pares, ambas orientaciones) y
//     swap-2 (par <-> nodo) entre rutas, con deltas penalizados O(1) en el marco granular.
//  3. PUNTO DE ENTRADA senda_solve: recibe coordenadas o una matriz, construye la matriz
//     redondeada en C++ y, si no hay solución inicial, construye una (BFD con flota acotada,
//     vecino más cercano en otro caso). Python solo lee datos y verifica.
//  4. PORTAFOLIO: senda_solve_multi_par corre varias configuraciones y semillas en hilos, con
//     elección determinista entre los candidatos (el presupuesto de cada corrida es tiempo de
//     reloj y depende del número de hilos, así que los candidatos pueden variar entre equipos).
// Ideas publicadas que implementa: ver docs/ACADEMIC_NOTES.md.
//
// Compilar: python -m lattimex build   (o: g++ -O3 -shared -fPIC -o libsenda.so senda_core.cpp)

#include <vector>
#include <algorithm>
#include <random>
#include <chrono>
#include <cmath>
#include <cstring>
#include <cstdint>
#include <numeric>
#include <thread>
#include <atomic>
#include <mutex>

using std::vector;

static inline double now_s() {
    using namespace std::chrono;
    return duration<double>(steady_clock::now().time_since_epoch()).count();
}

struct Ctx {
    int n = 0;
    vector<int32_t> Dstore;       // owned matrix when built from coords
    const int32_t* D = nullptr;
    vector<int> dem;
    int cap = 0, depot = 0, fleet = -1;
    vector<int> customers;
    vector<vector<int>> nbr;
    bool symmetric = true;
    bool useSegment = true;
    bool useExchangeReinsert = true;
    bool useOrOpt3 = false;       // relocate-3 (Or-opt triple); bit 4 of use_segment_moves
    long long evals = 0;
    inline int d(int a, int b) const { return D[(size_t)a * n + b]; }
};

typedef vector<vector<int>> Sol;

static inline long long ex_load(const Ctx& c, long long load) {
    return load > c.cap ? load - c.cap : 0;
}

static long long total_dist(const Ctx& c, const Sol& routes) {
    long long t = 0;
    for (const auto& r : routes) {
        if (r.empty()) continue;
        t += c.d(c.depot, r.front());
        for (size_t i = 0; i + 1 < r.size(); ++i) t += c.d(r[i], r[i + 1]);
        t += c.d(r.back(), c.depot);
    }
    return t;
}

static int route_load(const Ctx& c, const vector<int>& r) {
    int l = 0;
    for (int v : r) l += c.dem[v];
    return l;
}

static long long total_excess(const Ctx& c, const Sol& routes) {
    long long e = 0;
    for (const auto& r : routes) e += ex_load(c, route_load(c, r));
    return e;
}

static double pcost(const Ctx& c, const Sol& routes, double penalty) {
    return (double)total_dist(c, routes) + penalty * (double)total_excess(c, routes);
}

static void clean(Sol& routes) {
    routes.erase(std::remove_if(routes.begin(), routes.end(),
                                [](const vector<int>& r) { return r.empty(); }),
                 routes.end());
}

static bool feasible(const Ctx& c, const Sol& routes) {
    int nonEmpty = 0;
    for (const auto& r : routes) {
        if (r.empty()) continue;
        ++nonEmpty;
        if (route_load(c, r) > c.cap) return false;
    }
    if (c.fleet >= 0 && nonEmpty > c.fleet) return false;
    return true;
}

static bool exchange_reinsert_pass(const Ctx& c, Sol& routes, double penalty, bool hard,
                           double deadline);

// ---------------------------------------------------------------------------
// Granular local search, penalized objective
// ---------------------------------------------------------------------------

struct LSState {
    Sol routes;
    vector<int> routeOf, posOf;
    vector<int> loads;
    vector<vector<int>> prefix;

    void init(const Ctx& c, const Sol& in) {
        routes.clear();
        for (const auto& r : in) if (!r.empty()) routes.push_back(r);
        routeOf.assign(c.n, -1);
        posOf.assign(c.n, -1);
        loads.assign(routes.size(), 0);
        prefix.assign(routes.size(), {});
        for (size_t ri = 0; ri < routes.size(); ++ri) refresh(c, (int)ri);
    }
    void refresh(const Ctx& c, int ri) {
        int acc = 0;
        auto& r = routes[ri];
        prefix[ri].resize(r.size());
        for (size_t p = 0; p < r.size(); ++p) {
            routeOf[r[p]] = ri;
            posOf[r[p]] = (int)p;
            acc += c.dem[r[p]];
            prefix[ri][p] = acc;
        }
        loads[ri] = acc;
    }
    inline void pn(const Ctx& c, int v, int& prev, int& next) const {
        int ri = routeOf[v], p = posOf[v];
        const auto& r = routes[ri];
        prev = (p == 0) ? c.depot : r[p - 1];
        next = (p == (int)r.size() - 1) ? c.depot : r[p + 1];
    }
};

// Penalized granular LS. All load checks replaced by penalized deltas.
static void granular_ls(const Ctx& ctx, Ctx& mut, Sol& routes, double deadline,
                        uint64_t seed, double penalty) {
    LSState st;
    st.init(ctx, routes);
    if (st.routes.empty()) { routes = st.routes; return; }

    vector<int> order;
    for (const auto& r : st.routes) for (int v : r) order.push_back(v);
    std::mt19937_64 rng(seed);
    std::shuffle(order.begin(), order.end(), rng);

    vector<uint8_t> dontLook(ctx.n, 0);
    long long evals = 0;
    const bool sym = ctx.symmetric;
    const bool seg = ctx.useSegment;
    const double EPS = 1e-9;

    auto exi = [&](long long load) -> double {
        return load > ctx.cap ? (double)(load - ctx.cap) : 0.0;
    };

    auto reset = [&](std::initializer_list<int> nodes) {
        for (int v : nodes) if (v != ctx.depot && v >= 0) dontLook[v] = 0;
    };

    auto tryImprove = [&](int u) -> bool {
        if (now_s() >= deadline) return false;
        int ra = st.routeOf[u];
        int pu, nu; st.pn(ctx, u, pu, nu);
        int du = ctx.dem[u];
        int removeGain1 = ctx.d(pu, u) + ctx.d(u, nu) - ctx.d(pu, nu);
        // pair (u, x=nu) data for segment moves
        int x = nu;                       // partner for relocate-2 / swap-2
        bool hasPair = seg && (x != ctx.depot);
        int nx = ctx.depot, dx = 0, removeGain2 = 0;
        if (hasPair) {
            int px_, nx_;
            st.pn(ctx, x, px_, nx_);
            nx = nx_;
            dx = ctx.dem[x];
            removeGain2 = ctx.d(pu, u) + ctx.d(x, nx) - ctx.d(pu, nx); // inner edge d(u,x) kept
        }
        // triple (u, x, y=nx) data for Or-opt-3
        bool hasTriple = ctx.useOrOpt3 && hasPair && (nx != ctx.depot);
        int y = nx, ny = ctx.depot, dy = 0, removeGain3 = 0;
        if (hasTriple) {
            int py_, ny_;
            st.pn(ctx, y, py_, ny_);
            ny = ny_;
            dy = ctx.dem[y];
            removeGain3 = ctx.d(pu, u) + ctx.d(y, ny) - ctx.d(pu, ny); // inner edges kept
        }
        double exA = exi(st.loads[ra]);

        for (int v : ctx.nbr[u]) {
            if (now_s() >= deadline) return false;
            int rb = st.routeOf[v];
            if (rb < 0) continue;
            int pv, nv; st.pn(ctx, v, pv, nv);
            double exB = exi(st.loads[rb]);

            // --- relocate-1: u next to v ------------------------------------
            if (rb != ra || (v != pu && v != nu)) {
                const int xs[2] = {v, pv};
                const int ys[2] = {nv, v};
                for (int t = 0; t < 2; ++t) {
                    int xx = xs[t], yy = ys[t];
                    if (xx == u || yy == u) continue;
                    ++evals;
                    double delta = ctx.d(xx, u) + ctx.d(u, yy) - ctx.d(xx, yy) - removeGain1;
                    if (rb != ra)
                        delta += penalty * (exi(st.loads[ra] - du) - exA
                                          + exi(st.loads[rb] + du) - exB);
                    if (delta < -EPS) {
                        auto& src = st.routes[ra];
                        src.erase(src.begin() + st.posOf[u]);
                        int target = (xx != ctx.depot) ? st.routeOf[xx] : st.routeOf[yy];
                        auto& dst = st.routes[target];
                        int ipos = 0;
                        if (xx != ctx.depot)
                            ipos = (int)(std::find(dst.begin(), dst.end(), xx) - dst.begin()) + 1;
                        dst.insert(dst.begin() + ipos, u);
                        st.refresh(ctx, ra);
                        if (target != ra) st.refresh(ctx, target);
                        reset({u, v, pu, nu, xx, yy});
                        return true;
                    }
                }
            }

            // --- relocate-2 (Or-opt pair, inter-route, both orientations) ---
            if (hasPair && rb != ra && v != x && nv != u) {
                for (int orient = 0; orient < 2; ++orient) {
                    int a1 = orient == 0 ? u : x;
                    int a2 = orient == 0 ? x : u;
                    ++evals;
                    double delta = ctx.d(v, a1) + ctx.d(a2, nv) - ctx.d(v, nv)
                                 - removeGain2
                                 + (orient == 1 ? (double)(ctx.d(x, u) - ctx.d(u, x)) : 0.0)
                                 + penalty * (exi(st.loads[ra] - du - dx) - exA
                                            + exi(st.loads[rb] + du + dx) - exB);
                    if (delta < -EPS) {
                        auto& src = st.routes[ra];
                        int p = st.posOf[u];
                        src.erase(src.begin() + p, src.begin() + p + 2);
                        auto& dst = st.routes[rb];
                        int ipos = st.posOf[v] + 1;
                        dst.insert(dst.begin() + ipos, {a1, a2});
                        st.refresh(ctx, ra);
                        st.refresh(ctx, rb);
                        reset({u, x, v, pu, nx, nv});
                        return true;
                    }
                }
            }

            // --- relocate-3 (Or-opt triple, inter-route, both orientations) --
            if (hasTriple && rb != ra && v != x && v != y && nv != u) {
                for (int orient = 0; orient < 2; ++orient) {
                    int a1 = orient == 0 ? u : y;
                    int a3 = orient == 0 ? y : u;
                    ++evals;
                    double delta = ctx.d(v, a1) + ctx.d(a3, nv) - ctx.d(v, nv)
                                 - removeGain3
                                 + (orient == 1 ? (double)(ctx.d(y, x) + ctx.d(x, u)
                                                           - ctx.d(u, x) - ctx.d(x, y)) : 0.0)
                                 + penalty * (exi(st.loads[ra] - du - dx - dy) - exA
                                            + exi(st.loads[rb] + du + dx + dy) - exB);
                    if (delta < -EPS) {
                        auto& src = st.routes[ra];
                        int p = st.posOf[u];
                        src.erase(src.begin() + p, src.begin() + p + 3);
                        auto& dst = st.routes[rb];
                        int ipos = st.posOf[v] + 1;
                        if (orient == 0) dst.insert(dst.begin() + ipos, {u, x, y});
                        else dst.insert(dst.begin() + ipos, {y, x, u});
                        st.refresh(ctx, ra);
                        st.refresh(ctx, rb);
                        reset({u, x, y, v, pu, ny, nv});
                        return true;
                    }
                }
            }

            // --- Or-opt intra-route: move pair/triple within the same route --
            if (ctx.useOrOpt3 && rb == ra) {
                if (hasPair && v != u && v != x && v != pu && nv != u) {
                    ++evals;
                    double delta = ctx.d(v, u) + ctx.d(x, nv) - ctx.d(v, nv) - removeGain2;
                    if (delta < -EPS) {
                        auto& r = st.routes[ra];
                        int p = st.posOf[u];
                        int pvIdx = st.posOf[v];
                        r.erase(r.begin() + p, r.begin() + p + 2);
                        int ipos = pvIdx + 1 - (pvIdx > p ? 2 : 0);
                        r.insert(r.begin() + ipos, {u, x});
                        st.refresh(ctx, ra);
                        reset({u, x, v, pu, nx, nv});
                        return true;
                    }
                }
                if (hasTriple && v != u && v != x && v != y && v != pu && nv != u) {
                    ++evals;
                    double delta = ctx.d(v, u) + ctx.d(y, nv) - ctx.d(v, nv) - removeGain3;
                    if (delta < -EPS) {
                        auto& r = st.routes[ra];
                        int p = st.posOf[u];
                        int pvIdx = st.posOf[v];
                        r.erase(r.begin() + p, r.begin() + p + 3);
                        int ipos = pvIdx + 1 - (pvIdx > p ? 3 : 0);
                        r.insert(r.begin() + ipos, {u, x, y});
                        st.refresh(ctx, ra);
                        reset({u, x, y, v, pu, ny, nv});
                        return true;
                    }
                }
            }

            // --- swap-1: u <-> v --------------------------------------------
            if (rb != ra) {
                ++evals;
                int dv = ctx.dem[v];
                double delta = ctx.d(pu, v) + ctx.d(v, nu) - ctx.d(pu, u) - ctx.d(u, nu)
                             + ctx.d(pv, u) + ctx.d(u, nv) - ctx.d(pv, v) - ctx.d(v, nv)
                             + penalty * (exi(st.loads[ra] - du + dv) - exA
                                        + exi(st.loads[rb] - dv + du) - exB);
                if (delta < -EPS) {
                    st.routes[ra][st.posOf[u]] = v;
                    st.routes[rb][st.posOf[v]] = u;
                    st.refresh(ctx, ra);
                    st.refresh(ctx, rb);
                    reset({u, v, pu, nu, pv, nv});
                    return true;
                }
            } else if (v != pu && v != nu) {
                ++evals;
                double delta = ctx.d(pu, v) + ctx.d(v, nu) - ctx.d(pu, u) - ctx.d(u, nu)
                             + ctx.d(pv, u) + ctx.d(u, nv) - ctx.d(pv, v) - ctx.d(v, nv);
                if (delta < -EPS) {
                    st.routes[ra][st.posOf[u]] = v;
                    st.routes[rb][st.posOf[v]] = u;
                    st.refresh(ctx, ra);
                    reset({u, v, pu, nu, pv, nv});
                    return true;
                }
            }

            // --- swap-2: pair (u,x) <-> single v (inter-route) --------------
            if (hasPair && rb != ra && v != x) {
                ++evals;
                int dv = ctx.dem[v];
                double delta = ctx.d(pu, v) + ctx.d(v, nx) - ctx.d(pu, u) - ctx.d(x, nx)
                             + ctx.d(pv, u) + ctx.d(x, nv) - ctx.d(pv, v) - ctx.d(v, nv)
                             + penalty * (exi(st.loads[ra] - du - dx + dv) - exA
                                        + exi(st.loads[rb] - dv + du + dx) - exB);
                if (delta < -EPS) {
                    auto& A = st.routes[ra];
                    auto& B = st.routes[rb];
                    int p = st.posOf[u];
                    int q = st.posOf[v];
                    A.erase(A.begin() + p, A.begin() + p + 2);
                    A.insert(A.begin() + p, v);
                    B.erase(B.begin() + q);
                    B.insert(B.begin() + q, {u, x});
                    st.refresh(ctx, ra);
                    st.refresh(ctx, rb);
                    reset({u, x, v, pu, nx, pv, nv});
                    return true;
                }
            }

            // --- intra-route 2-opt -------------------------------------------
            if (rb == ra && sym) {
                int i = st.posOf[u], j = st.posOf[v];
                if (std::abs(i - j) > 1) {
                    int a = u, b = v;
                    if (i > j) std::swap(a, b);
                    int pa = st.posOf[a], pb = st.posOf[b];
                    auto& r = st.routes[ra];
                    int na = r[pa + 1];
                    int nb = (pb == (int)r.size() - 1) ? ctx.depot : r[pb + 1];
                    ++evals;
                    double delta = ctx.d(a, b) + ctx.d(na, nb) - ctx.d(a, na) - ctx.d(b, nb);
                    if (delta < -EPS) {
                        std::reverse(r.begin() + pa + 1, r.begin() + pb + 1);
                        st.refresh(ctx, ra);
                        reset({a, b, na, nb});
                        return true;
                    }
                }
            }

            // --- inter-route 2-opt* -------------------------------------------
            if (rb != ra) {
                ++evals;
                int prefA = st.prefix[ra][st.posOf[u]];
                int prefB = st.prefix[rb][st.posOf[v]];
                int tailA = st.loads[ra] - prefA;
                int tailB = st.loads[rb] - prefB;
                double delta = ctx.d(u, nv) + ctx.d(v, nu) - ctx.d(u, nu) - ctx.d(v, nv)
                             + penalty * (exi(prefA + tailB) - exA + exi(prefB + tailA) - exB);
                if (delta < -EPS) {
                    auto& A = st.routes[ra];
                    auto& B = st.routes[rb];
                    int ia = st.posOf[u], ib = st.posOf[v];
                    vector<int> newA(A.begin(), A.begin() + ia + 1);
                    newA.insert(newA.end(), B.begin() + ib + 1, B.end());
                    vector<int> newB(B.begin(), B.begin() + ib + 1);
                    newB.insert(newB.end(), A.begin() + ia + 1, A.end());
                    st.routes[ra] = std::move(newA);
                    st.routes[rb] = std::move(newB);
                    st.refresh(ctx, ra);
                    st.refresh(ctx, rb);
                    reset({u, v, nu, nv});
                    return true;
                }
            }
        }
        return false;
    };

    bool improvedAny = true;
    while (improvedAny && now_s() < deadline) {
        improvedAny = false;
        for (int u : order) {
            if (now_s() >= deadline) break;
            if (dontLook[u]) continue;
            if (st.routeOf[u] < 0) continue;
            if (tryImprove(u)) improvedAny = true;
            else dontLook[u] = 1;
        }
    }
    routes = st.routes;
    clean(routes);
    mut.evals += evals;
}

// ---------------------------------------------------------------------------
// Ejection exchange + fleet repair (feasible-space polish operators, from v1)
// ---------------------------------------------------------------------------

static int best_insert_one(const Ctx& c, const vector<int>& route, int node,
                           vector<int>& out) {
    int bestDelta = 0, bestPos = -1;
    for (int pos = 0; pos <= (int)route.size(); ++pos) {
        int prev = (pos == 0) ? c.depot : route[pos - 1];
        int next = (pos == (int)route.size()) ? c.depot : route[pos];
        int delta = c.d(prev, node) + c.d(node, next) - c.d(prev, next);
        if (bestPos < 0 || delta < bestDelta) { bestDelta = delta; bestPos = pos; }
    }
    out = route;
    out.insert(out.begin() + bestPos, node);
    return bestDelta;
}

static void best_insert_many(const Ctx& c, const vector<int>& route,
                             const vector<int>& nodes, vector<int>& out) {
    if (nodes.empty()) { out = route; return; }
    vector<int> orderA = nodes, orderB = nodes;
    if (nodes.size() == 2) std::swap(orderB[0], orderB[1]);
    long long bestCost = -1;
    for (int t = 0; t < (nodes.size() == 2 ? 2 : 1); ++t) {
        const auto& ord = (t == 0) ? orderA : orderB;
        vector<int> cur = route, tmp;
        for (int v : ord) { best_insert_one(c, cur, v, tmp); cur = tmp; }
        Sol w{cur};
        long long cost = total_dist(c, w);
        if (bestCost < 0 || cost < bestCost) { bestCost = cost; out = cur; }
    }
}

static bool ejection_exchange(const Ctx& c, Sol& routes, double deadline) {
    long long bestCost = total_dist(c, routes);
    int bestSrc = -1, bestTgt = -1;
    vector<int> bestNewSrc, bestNewTgt;
    vector<int> loads(routes.size());
    for (size_t i = 0; i < routes.size(); ++i) loads[i] = route_load(c, routes[i]);
    long long baseTotal = bestCost;

    for (size_t si = 0; si < routes.size(); ++si) {
        if (now_s() >= deadline) break;
        const auto& src = routes[si];
        for (size_t sp = 0; sp < src.size(); ++sp) {
            if (now_s() >= deadline) break;
            int incoming = src[sp];
            vector<int> srcWithout = src;
            srcWithout.erase(srcWithout.begin() + sp);
            int srcLoadWithout = loads[si] - c.dem[incoming];
            Sol full{src};
            long long srcCost = total_dist(c, full);

            for (size_t ti = 0; ti < routes.size(); ++ti) {
                if (ti == si) continue;
                if (now_s() >= deadline) break;
                if (loads[ti] + c.dem[incoming] <= c.cap) continue;
                const auto& tgt = routes[ti];
                Sol tw{tgt};
                long long tgtCost = total_dist(c, tw);
                int m = (int)tgt.size();
                for (int e1 = 0; e1 < m; ++e1) {
                    for (int e2 = e1; e2 < m; ++e2) {
                        if (now_s() >= deadline) break;
                        vector<int> ejected{tgt[e1]};
                        if (e2 != e1) ejected.push_back(tgt[e2]);
                        int ejLoad = 0;
                        for (int v : ejected) ejLoad += c.dem[v];
                        if (loads[ti] - ejLoad + c.dem[incoming] > c.cap) continue;
                        if (srcLoadWithout + ejLoad > c.cap) continue;
                        vector<int> tgtWithout;
                        for (int p = 0; p < m; ++p)
                            if (p != e1 && p != e2) tgtWithout.push_back(tgt[p]);
                        vector<int> newTgt, newSrc;
                        best_insert_one(c, tgtWithout, incoming, newTgt);
                        best_insert_many(c, srcWithout, ejected, newSrc);
                        Sol a{newTgt}, b{newSrc};
                        long long cand = baseTotal - srcCost - tgtCost
                                       + total_dist(c, a) + total_dist(c, b);
                        if (cand < bestCost) {
                            bestCost = cand;
                            bestSrc = (int)si; bestTgt = (int)ti;
                            bestNewSrc = newSrc; bestNewTgt = newTgt;
                        }
                    }
                }
            }
        }
    }
    if (bestSrc >= 0) {
        routes[bestSrc] = bestNewSrc;
        routes[bestTgt] = bestNewTgt;
        clean(routes);
        return true;
    }
    return false;
}

static bool eliminate_one_route(const Ctx& c, Sol& routes, double deadline) {
    long long bestCost = -1;
    Sol bestSol;
    vector<size_t> order(routes.size());
    for (size_t i = 0; i < order.size(); ++i) order[i] = i;
    std::sort(order.begin(), order.end(), [&](size_t a, size_t b) {
        if (routes[a].size() != routes[b].size()) return routes[a].size() < routes[b].size();
        return route_load(c, routes[a]) < route_load(c, routes[b]);
    });
    for (size_t oi = 0; oi < order.size(); ++oi) {
        if (now_s() >= deadline) break;
        size_t rem = order[oi];
        Sol cand;
        for (size_t i = 0; i < routes.size(); ++i)
            if (i != rem) cand.push_back(routes[i]);
        vector<int> loads(cand.size());
        for (size_t i = 0; i < cand.size(); ++i) loads[i] = route_load(c, cand[i]);
        vector<int> nodes = routes[rem];
        std::sort(nodes.begin(), nodes.end(),
                  [&](int a, int b) { return c.dem[a] > c.dem[b]; });
        bool ok = true;
        for (int v : nodes) {
            int bd = 0, bri = -1, bpos = -1;
            for (size_t ri = 0; ri < cand.size(); ++ri) {
                if (loads[ri] + c.dem[v] > c.cap) continue;
                for (int pos = 0; pos <= (int)cand[ri].size(); ++pos) {
                    int prev = (pos == 0) ? c.depot : cand[ri][pos - 1];
                    int next = (pos == (int)cand[ri].size()) ? c.depot : cand[ri][pos];
                    int delta = c.d(prev, v) + c.d(v, next) - c.d(prev, next);
                    if (bri < 0 || delta < bd) { bd = delta; bri = (int)ri; bpos = pos; }
                }
            }
            if (bri < 0) { ok = false; break; }
            cand[bri].insert(cand[bri].begin() + bpos, v);
            loads[bri] += c.dem[v];
        }
        if (!ok) continue;
        long long cost = total_dist(c, cand);
        if (bestCost < 0 || cost < bestCost) { bestCost = cost; bestSol = cand; }
    }
    if (bestCost >= 0) { routes = bestSol; return true; }
    return false;
}

static void repair_fleet(const Ctx& c, Sol& routes, double timeLimit) {
    if (c.fleet < 0) return;
    double deadline = now_s() + std::max(0.0, timeLimit);
    clean(routes);
    while ((int)routes.size() > c.fleet && now_s() < deadline) {
        if (!eliminate_one_route(c, routes, deadline)) break;
    }
}

static void granular_polish(const Ctx& ctx, Ctx& mut, Sol& routes, double timeLimit,
                            uint64_t seed, double penalty, int exchangeMaxPasses = -1) {
    double deadline = now_s() + std::max(0.0, timeLimit);
    granular_ls(ctx, mut, routes, deadline, seed, penalty);
    if (total_excess(ctx, routes) > 0)
        granular_ls(ctx, mut, routes, deadline, seed + 1, penalty * 10.0);
    if (ctx.useExchangeReinsert) {
        int swapPasses = 0;
        while (now_s() < deadline &&
               (exchangeMaxPasses < 0 || swapPasses < exchangeMaxPasses) &&
               exchange_reinsert_pass(ctx, routes, penalty, false, deadline)) {
            ++swapPasses;
            granular_ls(ctx, mut, routes, deadline, seed, penalty);
        }
    }
    long long best = total_dist(ctx, routes);
    while (now_s() < deadline && feasible(ctx, routes)) {
        Sol cand = routes;
        if (!ejection_exchange(ctx, cand, deadline)) break;
        granular_ls(ctx, mut, cand, deadline, seed, penalty * 10.0);
        long long cc = total_dist(ctx, cand);
        if (feasible(ctx, cand) && cc < best) { routes = cand; best = cc; }
        else break;
    }
}

// ---------------------------------------------------------------------------
// Exchange with best reinsertion: exchange u in A and v in B, each reinserted at its BEST
// position in the other route. Metric-agnostic adaptation: route pairs are
// limited via the granular neighbor graph instead of polar sectors.
// Includes the relocate-star variant (u alone to its best position in B).
// ---------------------------------------------------------------------------

struct InsSlot { double delta; int prev, next; };

struct Top3 {
    InsSlot s[3];
    int cnt = 0;
    void add(double delta, int prev, int next) {
        if (cnt < 3) {
            s[cnt++] = {delta, prev, next};
            for (int i = cnt - 1; i > 0 && s[i].delta < s[i-1].delta; --i) std::swap(s[i], s[i-1]);
        } else if (delta < s[2].delta) {
            s[2] = {delta, prev, next};
            for (int i = 2; i > 0 && s[i].delta < s[i-1].delta; --i) std::swap(s[i], s[i-1]);
        }
    }
};

static void top3_into(const Ctx& c, int u, const vector<int>& route, Top3& out) {
    out.cnt = 0;
    int prev = c.depot;
    for (size_t p = 0; p <= route.size(); ++p) {
        int next = (p == route.size()) ? c.depot : route[p];
        out.add((double)(c.d(prev, u) + c.d(u, next) - c.d(prev, next)), prev, next);
        prev = next;
    }
}

// best insertion of u into route of v with v removed (avoid slots adjacent to v)
static bool best_insert_avoiding(const Ctx& c, const Top3& t3, int u, int v,
                                 int pv, int nv, double& delta, int& prevOut) {
    bool found = false;
    for (int i = 0; i < t3.cnt; ++i) {
        if (t3.s[i].prev == v || t3.s[i].next == v) continue;
        delta = t3.s[i].delta; prevOut = t3.s[i].prev; found = true; break;
    }
    double inPlace = (double)(c.d(pv, u) + c.d(u, nv) - c.d(pv, nv));
    if (!found || inPlace < delta) { delta = inPlace; prevOut = pv; found = true; }
    return found;
}

static bool exchange_reinsert_pass(const Ctx& c, Sol& routes, double penalty, bool hard,
                           double deadline) {
    clean(routes);
    int R = (int)routes.size();
    if (R < 2) return false;
    vector<int> loads(R), routeOf(c.n, -1), posOf(c.n, -1);
    for (int ri = 0; ri < R; ++ri) {
        loads[ri] = route_load(c, routes[ri]);
        for (size_t p = 0; p < routes[ri].size(); ++p) {
            routeOf[routes[ri][p]] = ri;
            posOf[routes[ri][p]] = (int)p;
        }
    }
    auto exi = [&](long long l) -> double { return l > c.cap ? (double)(l - c.cap) : 0.0; };
    auto pn = [&](int v, int& prev, int& next) {
        int ri = routeOf[v], p = posOf[v];
        prev = (p == 0) ? c.depot : routes[ri][p - 1];
        next = (p == (int)routes[ri].size() - 1) ? c.depot : routes[ri][p + 1];
    };

    // close route pairs via granular neighbors
    vector<uint8_t> mark((size_t)R * R, 0);
    vector<std::pair<int,int>> pairs;
    for (int u : c.customers) {
        if (now_s() >= deadline) return false;
        int a = routeOf[u];
        if (a < 0) continue;
        for (int w : c.nbr[u]) {
            int b = routeOf[w];
            if (b < 0 || b == a) continue;
            int lo = std::min(a, b), hi = std::max(a, b);
            if (!mark[(size_t)lo * R + hi]) { mark[(size_t)lo * R + hi] = 1; pairs.push_back({lo, hi}); }
        }
    }

    const double EPS = 1e-9;
    double bestCost = -EPS;
    int bU = -1, bV = -1, bA = -1, bB = -1, bPrevU = 0, bPrevV = 0;
    bool isReloc = false;

    Top3 t3;
    vector<Top3> uIntoB, vIntoA;
    for (auto& pr : pairs) {
        if (now_s() >= deadline) break;
        int a = pr.first, b = pr.second;
        const auto& A = routes[a];
        const auto& B = routes[b];
        uIntoB.assign(A.size(), Top3());
        vIntoA.assign(B.size(), Top3());
        for (size_t i = 0; i < A.size(); ++i) {
            if (now_s() >= deadline) return false;
            top3_into(c, A[i], B, uIntoB[i]);
        }
        for (size_t j = 0; j < B.size(); ++j) {
            if (now_s() >= deadline) return false;
            top3_into(c, B[j], A, vIntoA[j]);
        }

        for (size_t i = 0; i < A.size(); ++i) {
            if (now_s() >= deadline) return false;
            int u = A[i];
            int pu, nu; pn(u, pu, nu);
            double remU = (double)(c.d(pu, u) + c.d(u, nu) - c.d(pu, nu));
            int du = c.dem[u];

            // relocate-star: u to best position in B
            {
                long long newLa = loads[a] - du, newLb = loads[b] + du;
                bool ok = !hard || (newLb <= c.cap);
                if (ok && uIntoB[i].cnt > 0) {
                    double cost = uIntoB[i].s[0].delta - remU;
                    if (!hard) cost += penalty * (exi(newLa) - exi(loads[a]) + exi(newLb) - exi(loads[b]));
                    if (cost < bestCost) {
                        bestCost = cost; isReloc = true;
                        bU = u; bV = -1; bA = a; bB = b; bPrevU = uIntoB[i].s[0].prev;
                    }
                }
            }

            for (size_t j = 0; j < B.size(); ++j) {
                if (now_s() >= deadline) return false;
                int v = B[j];
                int pv, nv; pn(v, pv, nv);
                double remV = (double)(c.d(pv, v) + c.d(v, nv) - c.d(pv, nv));
                int dv = c.dem[v];
                long long newLa = loads[a] - du + dv, newLb = loads[b] - dv + du;
                if (hard && (newLa > c.cap || newLb > c.cap)) continue;
                // quick lower-bound filter
                double lb = -remU - remV;
                if (!hard) lb += penalty * (exi(newLa) - exi(loads[a]) + exi(newLb) - exi(loads[b]));
                if (lb >= bestCost) continue;
                double extraU, extraV; int prevU, prevV;
                if (!best_insert_avoiding(c, uIntoB[i], u, v, pv, nv, extraU, prevU)) continue;
                if (!best_insert_avoiding(c, vIntoA[j], v, u, pu, nu, extraV, prevV)) continue;
                double cost = extraU + extraV - remU - remV;
                if (!hard) cost += penalty * (exi(newLa) - exi(loads[a]) + exi(newLb) - exi(loads[b]));
                if (cost < bestCost) {
                    bestCost = cost; isReloc = false;
                    bU = u; bV = v; bA = a; bB = b; bPrevU = prevU; bPrevV = prevV;
                }
            }
        }
    }

    if (bU < 0) return false;
    auto insert_after = [&](vector<int>& route, int prev, int node) {
        if (prev == c.depot) { route.insert(route.begin(), node); return; }
        auto it = std::find(route.begin(), route.end(), prev);
        if (it == route.end()) { route.push_back(node); return; }
        route.insert(it + 1, node);
    };
    auto& A = routes[bA];
    auto& B = routes[bB];
    A.erase(std::find(A.begin(), A.end(), bU));
    if (isReloc) {
        insert_after(B, bPrevU, bU);
    } else {
        B.erase(std::find(B.begin(), B.end(), bV));
        insert_after(B, bPrevU, bU);
        insert_after(A, bPrevV, bV);
    }
    clean(routes);
    return true;
}

// ---------------------------------------------------------------------------
// ALNS destroy / repair (penalized)
// ---------------------------------------------------------------------------

static void collect_nodes(const Sol& routes, vector<int>& out) {
    out.clear();
    for (const auto& r : routes) for (int v : r) out.push_back(v);
}

static void remove_set(const Sol& in, const vector<int>& removed, Sol& kept) {
    int mx = 0;
    for (const auto& r : in) for (int v : r) mx = std::max(mx, v);
    vector<uint8_t> rm(mx + 1, 0);
    for (int v : removed) if (v <= mx) rm[v] = 1;
    kept.clear();
    for (const auto& r : in) {
        vector<int> nr;
        for (int v : r) if (!rm[v]) nr.push_back(v);
        kept.push_back(std::move(nr));
    }
}

static void destroy_random(const Ctx& c, const Sol& cur, int count, std::mt19937_64& rng,
                           Sol& kept, vector<int>& removed) {
    vector<int> nodes; collect_nodes(cur, nodes);
    std::shuffle(nodes.begin(), nodes.end(), rng);
    removed.assign(nodes.begin(), nodes.begin() + std::min((size_t)count, nodes.size()));
    remove_set(cur, removed, kept);
}

static void destroy_worst(const Ctx& c, const Sol& cur, int count, std::mt19937_64& rng,
                          Sol& kept, vector<int>& removed) {
    vector<std::pair<int,int>> scored;
    for (const auto& r : cur) {
        for (size_t p = 0; p < r.size(); ++p) {
            int prev = (p == 0) ? c.depot : r[p - 1];
            int next = (p == r.size() - 1) ? c.depot : r[p + 1];
            scored.push_back({c.d(prev, r[p]) + c.d(r[p], next) - c.d(prev, next), r[p]});
        }
    }
    std::sort(scored.begin(), scored.end(), std::greater<>());
    removed.clear();
    std::uniform_real_distribution<double> U(0.0, 1.0);
    while (!scored.empty() && (int)removed.size() < count) {
        double u = U(rng);
        size_t idx = std::min((size_t)(scored.size() * u * u * u), scored.size() - 1);
        removed.push_back(scored[idx].second);
        scored.erase(scored.begin() + idx);
    }
    remove_set(cur, removed, kept);
}

static void destroy_shaw(const Ctx& c, const Sol& cur, int count, std::mt19937_64& rng,
                         Sol& kept, vector<int>& removed) {
    vector<int> pool; collect_nodes(cur, pool);
    removed.clear();
    if (pool.empty()) { kept = cur; return; }
    std::uniform_int_distribution<size_t> pick(0, pool.size() - 1);
    size_t s = pick(rng);
    removed.push_back(pool[s]);
    pool.erase(pool.begin() + s);
    std::uniform_real_distribution<double> U(0.0, 1.0);
    while (!pool.empty() && (int)removed.size() < count) {
        int ref = removed[(size_t)(U(rng) * removed.size())];
        std::sort(pool.begin(), pool.end(),
                  [&](int a, int b) { return c.d(ref, a) < c.d(ref, b); });
        double u = U(rng);
        size_t idx = std::min((size_t)(pool.size() * u * u * u), pool.size() - 1);
        removed.push_back(pool[idx]);
        pool.erase(pool.begin() + idx);
    }
    remove_set(cur, removed, kept);
}

static void destroy_route(const Ctx& c, const Sol& cur, int count, std::mt19937_64& rng,
                          Sol& kept, vector<int>& removed) {
    removed.clear(); kept.clear();
    if (cur.empty()) return;
    std::uniform_real_distribution<double> U(0.0, 1.0);
    int excess = (c.fleet >= 0) ? (int)cur.size() - c.fleet : 0;
    if (excess > 0) {
        vector<size_t> order(cur.size());
        for (size_t i = 0; i < order.size(); ++i) order[i] = i;
        std::sort(order.begin(), order.end(), [&](size_t a, size_t b) {
            return cur[a].size() < cur[b].size();
        });
        size_t nVictims = std::min((size_t)(excess + 1), cur.size() - 1);
        vector<uint8_t> victim(cur.size(), 0);
        for (size_t i = 0; i < nVictims; ++i) victim[order[i]] = 1;
        for (size_t i = 0; i < cur.size(); ++i) {
            if (victim[i]) { for (int v : cur[i]) removed.push_back(v); }
            else kept.push_back(cur[i]);
        }
        return;
    }
    std::uniform_int_distribution<size_t> pick(0, cur.size() - 1);
    size_t v1 = pick(rng);
    size_t v2 = v1;
    if (cur.size() > 2 && U(rng) < 0.4) v2 = pick(rng);
    for (size_t i = 0; i < cur.size(); ++i) {
        if (i == v1 || i == v2) {
            for (int v : cur[i]) removed.push_back(v);
        } else kept.push_back(cur[i]);
    }
}

struct InsOpt { double delta; int ri, pos; };

// Insertion options: feasible neighbor-adjacent + route ends; if none feasible,
// penalized overload options (the key v2 change for tight instances).
static void insertion_options(const Ctx& c, const Sol& routes, const vector<int>& loads,
                              int node, bool fleetOpen, const vector<int>& routeOfNode,
                              const vector<int>& posOfNode, double penalty,
                              vector<InsOpt>& out) {
    out.clear();
    int dem = c.dem[node];
    auto addOpt = [&](int ri, int pos, bool penalized) {
        const auto& r = routes[ri];
        int prev = (pos == 0) ? c.depot : r[pos - 1];
        int next = (pos == (int)r.size()) ? c.depot : r[pos];
        double delta = c.d(prev, node) + c.d(node, next) - c.d(prev, next);
        if (penalized) {
            long long before = ex_load(c, loads[ri]);
            long long after = ex_load(c, loads[ri] + dem);
            delta += penalty * (double)(after - before);
        }
        out.push_back({delta, ri, pos});
    };
    for (int v : c.nbr[node]) {
        int ri = routeOfNode[v];
        if (ri < 0 || loads[ri] + dem > c.cap) continue;
        addOpt(ri, posOfNode[v], false);
        addOpt(ri, posOfNode[v] + 1, false);
    }
    for (size_t ri = 0; ri < routes.size(); ++ri) {
        if (loads[ri] + dem > c.cap) continue;
        addOpt((int)ri, 0, false);
        addOpt((int)ri, (int)routes[ri].size(), false);
    }
    if (fleetOpen) out.push_back({2.0 * c.d(node, c.depot), (int)routes.size(), 0});
    if (out.empty()) {
        // overload options, penalized
        for (int v : c.nbr[node]) {
            int ri = routeOfNode[v];
            if (ri < 0) continue;
            addOpt(ri, posOfNode[v] + 1, true);
        }
        for (size_t ri = 0; ri < routes.size(); ++ri)
            addOpt((int)ri, (int)routes[ri].size(), true);
    }
}

static void index_routes(const Ctx& c, const Sol& routes, vector<int>& routeOf,
                         vector<int>& posOf) {
    routeOf.assign(c.n, -1);
    posOf.assign(c.n, -1);
    for (size_t ri = 0; ri < routes.size(); ++ri)
        for (size_t p = 0; p < routes[ri].size(); ++p) {
            routeOf[routes[ri][p]] = (int)ri;
            posOf[routes[ri][p]] = (int)p;
        }
}

static void do_insert(const Ctx& c, Sol& routes, vector<int>& loads, const InsOpt& o,
                      int node) {
    if (o.ri == (int)routes.size()) {
        routes.push_back({node});
        loads.push_back(c.dem[node]);
    } else {
        routes[o.ri].insert(routes[o.ri].begin() + o.pos, node);
        loads[o.ri] += c.dem[node];
    }
}

static void repair_regret(const Ctx& c, Sol& routes, vector<int> removed,
                          std::mt19937_64& rng, double penalty) {
    clean(routes);
    vector<int> loads(routes.size());
    for (size_t i = 0; i < routes.size(); ++i) loads[i] = route_load(c, routes[i]);
    std::shuffle(removed.begin(), removed.end(), rng);
    vector<int> routeOf, posOf;
    vector<InsOpt> opts;
    while (!removed.empty()) {
        index_routes(c, routes, routeOf, posOf);
        int bestNode = -1; InsOpt bestOpt{0, 0, 0};
        double bestRank0 = 0, bestRank1 = 0; bool first = true;
        for (int node : removed) {
            bool fleetOpen = c.fleet < 0 || (int)routes.size() < c.fleet;
            insertion_options(c, routes, loads, node, fleetOpen, routeOf, posOf, penalty, opts);
            if (opts.empty()) opts.push_back({2.0 * c.d(node, c.depot), (int)routes.size(), 0});
            std::sort(opts.begin(), opts.end(),
                      [](const InsOpt& a, const InsOpt& b) { return a.delta < b.delta; });
            double regret = (opts.size() > 1) ? opts[1].delta - opts[0].delta : 1e9;
            if (first || (-regret < bestRank0) ||
                (-regret == bestRank0 && opts[0].delta < bestRank1)) {
                first = false;
                bestRank0 = -regret;
                bestRank1 = opts[0].delta;
                bestNode = node;
                bestOpt = opts[0];
            }
        }
        do_insert(c, routes, loads, bestOpt, bestNode);
        removed.erase(std::find(removed.begin(), removed.end(), bestNode));
    }
}

static void repair_greedy(const Ctx& c, Sol& routes, vector<int> removed,
                          std::mt19937_64& rng, double penalty) {
    clean(routes);
    vector<int> loads(routes.size());
    for (size_t i = 0; i < routes.size(); ++i) loads[i] = route_load(c, routes[i]);
    std::shuffle(removed.begin(), removed.end(), rng);
    vector<int> routeOf, posOf;
    vector<InsOpt> opts;
    for (int node : removed) {
        index_routes(c, routes, routeOf, posOf);
        bool fleetOpen = c.fleet < 0 || (int)routes.size() < c.fleet;
        insertion_options(c, routes, loads, node, fleetOpen, routeOf, posOf, penalty, opts);
        if (opts.empty()) opts.push_back({2.0 * c.d(node, c.depot), (int)routes.size(), 0});
        auto it = std::min_element(opts.begin(), opts.end(),
                                   [](const InsOpt& a, const InsOpt& b) { return a.delta < b.delta; });
        do_insert(c, routes, loads, *it, node);
    }
}

// ---------------------------------------------------------------------------
// ALNS main loop, penalized with adaptive penalty
// ---------------------------------------------------------------------------

static thread_local long long g_iterations = 0;

struct RunOpts {
    int budgetMode = 0;              // 0 = wall-clock seconds, 1 = deterministic ALNS iterations
    long long alnsIterations = 0;
    int polishMode = 1;              // 0 = off, 1 = timed, 2 = full, 3 = capped full
    int exchangeMaxPasses = -1;      // -1 = unlimited while improving
    int bestPolishMaxCalls = -1;     // -1 = every new global best
    double destroyMin = 0.10;
    double destroyMax = 0.35;
    double candLsBudget = 0.08;      // <0 means run candidate LS to local optimum
    double repairLsBudget = 0.05;
    double bestPolishBudget = 0.15;
    long long stagnationLimit = 0;   // >0: stop after this many iterations without a new global best
    double t0Scale = 1.0;            // SA temperature scale (warm starts use < 1)
};

static Sol alns(const Ctx& ctx, Ctx& mut, Sol current, double timeLimit, uint64_t seed,
                double penalty0, int usePenalty, const RunOpts& opts = RunOpts()) {
    // Experimental ablation switch: preserve construction and initial polish,
    // but skip the ALNS loop. Existing callers use non-negative values.
    if (opts.alnsIterations < 0) {
        clean(current);
        g_iterations = 0;
        return current;
    }

    std::mt19937_64 rng(seed);
    std::uniform_real_distribution<double> U(0.0, 1.0);
    double started = now_s();
    bool iterationBudget = opts.budgetMode == 1;
    long long maxIterations = opts.alnsIterations > 0
        ? opts.alnsIterations
        : (long long)std::max(1.0, timeLimit);
    double deadline = iterationBudget ? started + 1.0e9 : started + std::max(0.0, timeLimit);

    clean(current);
    double penalty = penalty0;
    double curP = pcost(ctx, current, penalty);
    bool curFeas = feasible(ctx, current);

    Sol best = current;
    long long bestDist = total_dist(ctx, current);
    bool bestFeasible = curFeas;

    int n = 0;
    for (const auto& r : current) n += (int)r.size();
    if (n == 0) return best;

    double dW[4] = {1, 1, 1, 1};
    double rW[2] = {1, 1};
    const double decay = 0.99;
    double t0 = std::max(1.0, 0.02 * (double)bestDist) * opts.t0Scale;
    double tEnd = std::max(0.01, 0.0002 * (double)bestDist) * opts.t0Scale;
    long long iterations = 0;
    long long lastImprove = 0;
    long long stagLimit = opts.stagnationLimit >= 0 ? opts.stagnationLimit : -opts.stagnationLimit;
    int reheatsLeft = opts.stagnationLimit < 0 ? 2 : 0;  // negative limit: reheat instead of stop
    long long fracAnchor = 0;
    int feasCount = 0, windowCount = 0;
    int bestPolishCalls = 0;

    auto pick = [&](double* w, int m) {
        double tot = 0;
        for (int i = 0; i < m; ++i) tot += w[i];
        double shot = U(rng) * tot, acc = 0;
        for (int i = 0; i < m; ++i) { acc += w[i]; if (shot <= acc) return i; }
        return m - 1;
    };

    while (true) {
        double now = now_s();
        double remaining = deadline - now;
        if (iterationBudget) {
            if (iterations >= maxIterations) break;
            remaining = 1.0e9;
        } else if (remaining <= 0.005) break;
        if (stagLimit > 0 && iterations - lastImprove >= stagLimit) {
            if (reheatsLeft > 0) {
                --reheatsLeft;
                fracAnchor = iterations;
                lastImprove = iterations;
                t0 *= 0.6;  // partial reheat around the current basin
                current = best;
                curP = pcost(ctx, current, penalty);
                curFeas = feasible(ctx, current);
            } else {
                break;
            }
        }
        ++iterations;
        double frac = iterationBudget
            ? (double)(iterations - fracAnchor) / (double)std::max(1LL, maxIterations - fracAnchor)
            : (now - started) / std::max(timeLimit, 1e-9);
        double temp = t0 * std::pow(tEnd / t0, frac);

        int di = pick(dW, 4);
        int ri = pick(rW, 2);
        if (!curFeas && ctx.fleet >= 0 && U(rng) < 0.8) di = 3;

        std::uniform_real_distribution<double> F(opts.destroyMin, opts.destroyMax);
        int count = std::max(3, (int)(n * F(rng)));

        Sol kept; vector<int> removed;
        switch (di) {
            case 0: destroy_random(ctx, current, count, rng, kept, removed); break;
            case 1: destroy_worst(ctx, current, count, rng, kept, removed); break;
            case 2: destroy_shaw(ctx, current, count, rng, kept, removed); break;
            default: destroy_route(ctx, current, count, rng, kept, removed); break;
        }
        Sol candidate = kept;
        double repPen = usePenalty ? penalty : 1e9; // no-penalty mode: hard repair
        if (ri == 0) repair_regret(ctx, candidate, removed, rng, repPen);
        else repair_greedy(ctx, candidate, removed, rng, repPen);

        clean(candidate);
        if (ctx.fleet >= 0 && (int)candidate.size() > ctx.fleet) {
            double fleetRepairLimit = iterationBudget ? 1.0e9 : std::min(0.10, remaining * 0.2);
            repair_fleet(ctx, candidate, fleetRepairLimit);
            if ((int)candidate.size() > ctx.fleet) {
                dW[di] *= decay; rW[ri] *= decay;
                continue;
            }
        }
        double candDeadline = opts.candLsBudget < 0.0
            ? deadline
            : std::min(now_s() + opts.candLsBudget, deadline);
        granular_ls(ctx, mut, candidate, candDeadline, seed + iterations,
                    usePenalty ? penalty : 1e9);
        bool candFeas = total_excess(ctx, candidate) == 0
                        && (ctx.fleet < 0 || (int)candidate.size() <= ctx.fleet);
        // Repair: if infeasible, half the time retry at 10x penalty
        if (!candFeas && usePenalty && U(rng) < 0.5) {
            double repairDeadline = opts.repairLsBudget < 0.0
                ? deadline
                : std::min(now_s() + opts.repairLsBudget, deadline);
            granular_ls(ctx, mut, candidate, repairDeadline, seed + iterations + 7,
                        penalty * 10.0);
            candFeas = total_excess(ctx, candidate) == 0
                       && (ctx.fleet < 0 || (int)candidate.size() <= ctx.fleet);
        }
        double candP = pcost(ctx, candidate, penalty);
        long long candDist = total_dist(ctx, candidate);

        ++windowCount;
        if (candFeas) ++feasCount;

        double score = 0.0;
        bool accepted = false;
        double delta = candP - curP;
        if (candFeas && !curFeas) {
            accepted = true; score = 2.0;
        } else if (delta < 0 || U(rng) < std::exp(-delta / std::max(temp, 1e-9))) {
            accepted = true; score = (delta >= 0) ? 0.5 : 2.0;
        }
        if (candFeas && (!bestFeasible || candDist < bestDist)) {
            double rem2 = deadline - now_s();
            bool allowPolish = opts.polishMode != 0 &&
                (opts.bestPolishMaxCalls < 0 || bestPolishCalls < opts.bestPolishMaxCalls);
            if (allowPolish && (iterationBudget || rem2 > 0.03)) {
                ++bestPolishCalls;
                double polishLimit = 0.0;
                if (opts.polishMode == 1) polishLimit = std::min(opts.bestPolishBudget, rem2 * 0.3);
                else if (opts.polishMode == 2 || opts.polishMode == 3)
                    polishLimit = iterationBudget ? 1.0e9 : std::max(0.0, rem2 * 0.95);
                else polishLimit = opts.bestPolishBudget;
                int polishSwapPasses = (opts.polishMode == 3) ? opts.exchangeMaxPasses : -1;
                Sol pol = candidate;
                granular_polish(ctx, mut, pol, polishLimit, seed + iterations, penalty, polishSwapPasses);
                long long pd = total_dist(ctx, pol);
                if (feasible(ctx, pol) && pd <= candDist) { candidate = pol; candDist = pd; }
            }
            best = candidate;
            bestDist = candDist;
            bestFeasible = true;
            lastImprove = iterations;
            accepted = true; score = 5.0;
            candP = pcost(ctx, candidate, penalty);
        }
        if (accepted) {
            current = candidate;
            curP = candP;
            curFeas = candFeas;
        }
        dW[di] = dW[di] * decay + (1 - decay) * score;
        rW[ri] = rW[ri] * decay + (1 - decay) * score;

        // adaptive penalty toward ~30% feasible candidates
        if (usePenalty && windowCount >= 50) {
            double fr = (double)feasCount / windowCount;
            if (fr < 0.25) penalty = std::min(penalty * 1.25, 1e6);
            else if (fr > 0.45) penalty = std::max(penalty * 0.85, 0.1);
            curP = pcost(ctx, current, penalty);
            feasCount = 0; windowCount = 0;
        }
    }
    g_iterations = iterations;
    return best;
}

// ---------------------------------------------------------------------------
// Internal constructions
// ---------------------------------------------------------------------------

static Sol bfd_init(const Ctx& c) {
    int k = (c.fleet > 0) ? c.fleet : std::max(1, (int)std::ceil(
        (double)std::accumulate(c.dem.begin(), c.dem.end(), 0LL) / std::max(c.cap, 1)));
    vector<int> nodes = c.customers;
    std::sort(nodes.begin(), nodes.end(), [&](int a, int b) {
        if (c.dem[a] != c.dem[b]) return c.dem[a] > c.dem[b];
        return c.d(c.depot, a) > c.d(c.depot, b);
    });
    vector<vector<int>> bins(k);
    vector<int> loads(k, 0);
    for (int v : nodes) {
        int best = -1, bestResidual = INT32_MAX;
        for (int i = 0; i < k; ++i) {
            int residual = c.cap - loads[i] - c.dem[v];
            if (residual >= 0 && residual < bestResidual) { bestResidual = residual; best = i; }
        }
        if (best < 0)
            best = (int)(std::min_element(loads.begin(), loads.end()) - loads.begin());
        bins[best].push_back(v);
        loads[best] += c.dem[v];
    }
    Sol routes;
    for (auto& bin : bins) {
        vector<int> route;
        for (int v : bin) {
            int bestPos = 0, bestDelta = INT32_MAX;
            for (int pos = 0; pos <= (int)route.size(); ++pos) {
                int prev = (pos == 0) ? c.depot : route[pos - 1];
                int next = (pos == (int)route.size()) ? c.depot : route[pos];
                int delta = c.d(prev, v) + c.d(v, next) - c.d(prev, next);
                if (delta < bestDelta) { bestDelta = delta; bestPos = pos; }
            }
            route.insert(route.begin() + bestPos, v);
        }
        if (!route.empty()) routes.push_back(route);
    }
    return routes;
}

static Sol nn_init(const Ctx& c) {
    vector<uint8_t> used(c.n, 0);
    int remaining = (int)c.customers.size();
    Sol routes;
    while (remaining > 0) {
        vector<int> route;
        int load = 0, cur = c.depot;
        while (true) {
            int best = -1, bestD = INT32_MAX;
            for (int v : c.customers) {
                if (used[v] || load + c.dem[v] > c.cap) continue;
                int dd = c.d(cur, v);
                if (dd < bestD) { bestD = dd; best = v; }
            }
            if (best < 0) break;
            route.push_back(best);
            used[best] = 1; --remaining;
            load += c.dem[best];
            cur = best;
        }
        if (route.empty()) break;
        routes.push_back(route);
    }
    return routes;
}

static void build_neighbors(Ctx& ctx, int k) {
    int nc = (int)ctx.customers.size();
    int kEff = (nc <= 60) ? std::max(1, nc - 1) : k;
    ctx.nbr.assign(ctx.n, {});
    for (int u : ctx.customers) {
        vector<int> others;
        for (int v : ctx.customers) if (v != u) others.push_back(v);
        std::sort(others.begin(), others.end(),
                  [&](int a, int b) { return ctx.d(u, a) < ctx.d(u, b); });
        if ((int)others.size() > kEff) others.resize(kEff);
        ctx.nbr[u] = others;
    }
}

static double base_penalty(const Ctx& ctx) {
    int maxDist = 0, maxDem = 1;
    for (int u : ctx.customers) {
        maxDem = std::max(maxDem, ctx.dem[u]);
        maxDist = std::max(maxDist, ctx.d(ctx.depot, u));
    }
    return std::max(0.5, std::min(1000.0, (double)maxDist / (double)maxDem));
}

static Sol initial_routes(const Ctx& ctx, const int32_t* init_flat, int init_len) {
    Sol routes;
    if (init_len > 0) {
        vector<int> cur;
        for (int i = 0; i < init_len; ++i) {
            int v = init_flat[i];
            if (v == -2) break;
            if (v == -1) { if (!cur.empty()) routes.push_back(cur); cur.clear(); }
            else cur.push_back(v);
        }
        if (!cur.empty()) routes.push_back(cur);
    } else {
        routes = (ctx.fleet > 0) ? bfd_init(ctx) : nn_init(ctx);
    }
    return routes;
}

static int emit_solution(const Ctx& ctx, const Sol& sol, int32_t* out_flat, int out_cap) {
    int pos = 0;
    for (const auto& r : sol) {
        if (r.empty()) continue;
        for (int v : r) {
            if (pos >= out_cap - 2) return -1;
            out_flat[pos++] = v;
        }
        out_flat[pos++] = -1;
    }
    out_flat[pos++] = -2;
    return pos;
}
// ---------------------------------------------------------------------------
// C ABI
// ---------------------------------------------------------------------------

extern "C" {

int senda_solve(
    int n_nodes,
    const double* xs, const double* ys,      // coords (size n_nodes); used if dist==null
    const int32_t* dist,                     // optional flat matrix (may be null)
    const int32_t* demands,
    int capacity, int depot, int vehicle_hint,
    const int32_t* customer_ids, int n_customers,
    const int32_t* init_flat, int init_len,  // init_len==0 -> internal construction
    double time_limit_sec, uint64_t seed, int k,
    int use_segment_moves, int use_penalty,
    int32_t* out_flat, int out_cap,
    int64_t* out_info /* [0]=len [1]=iters [2]=evals [3]=dist [4]=feasible */) {

    double started = now_s();
    Ctx ctx;
    ctx.n = n_nodes;
    ctx.dem.assign(demands, demands + n_nodes);
    ctx.cap = capacity;
    ctx.depot = depot;
    ctx.fleet = vehicle_hint;
    ctx.useSegment = (use_segment_moves & 1) != 0;
    ctx.useExchangeReinsert = (use_segment_moves & 2) != 0;
    ctx.customers.assign(customer_ids, customer_ids + n_customers);

    if (dist != nullptr) {
        ctx.D = dist;
        ctx.symmetric = true;
        for (int a : ctx.customers) {
            for (int b : ctx.customers) if (b > a && ctx.d(a, b) != ctx.d(b, a)) {
                ctx.symmetric = false; break;
            }
            if (!ctx.symmetric) break;
        }
    } else {
        // build rounded-euclidean matrix in C++ (CVRPLIB convention)
        ctx.Dstore.assign((size_t)n_nodes * n_nodes, 0);
        vector<int> ids = ctx.customers;
        ids.push_back(depot);
        for (int a : ids) {
            for (int b : ids) {
                if (a == b) continue;
                double dx = xs[a] - xs[b], dy = ys[a] - ys[b];
                ctx.Dstore[(size_t)a * n_nodes + b] =
                    (int32_t)(std::sqrt(dx * dx + dy * dy) + 0.5);
            }
        }
        ctx.D = ctx.Dstore.data();
        ctx.symmetric = true;
    }

    // neighbor lists
    int nc = (int)ctx.customers.size();
    int kEff = (nc <= 60) ? std::max(1, nc - 1) : k;
    ctx.nbr.assign(ctx.n, {});
    for (int u : ctx.customers) {
        vector<int> others;
        for (int v : ctx.customers) if (v != u) others.push_back(v);
        std::sort(others.begin(), others.end(),
                  [&](int a, int b) { return ctx.d(u, a) < ctx.d(u, b); });
        if ((int)others.size() > kEff) others.resize(kEff);
        ctx.nbr[u] = others;
    }

    // base penalty, scaled by max distance / max demand
    int maxDist = 0, maxDem = 1;
    for (int u : ctx.customers) {
        maxDem = std::max(maxDem, ctx.dem[u]);
        maxDist = std::max(maxDist, ctx.d(ctx.depot, u));
    }
    double penalty0 = std::max(0.5, std::min(1000.0, (double)maxDist / (double)maxDem));

    double totalBudget = time_limit_sec;
    double deadline = started + totalBudget;
    Ctx& mut = ctx;

    // init
    Sol routes;
    if (init_len > 0) {
        vector<int> cur;
        for (int i = 0; i < init_len; ++i) {
            int v = init_flat[i];
            if (v == -2) break;
            if (v == -1) { if (!cur.empty()) routes.push_back(cur); cur.clear(); }
            else cur.push_back(v);
        }
        if (!cur.empty()) routes.push_back(cur);
    } else {
        routes = (ctx.fleet > 0) ? bfd_init(ctx) : nn_init(ctx);
    }
    if (ctx.fleet >= 0 && (int)routes.size() > ctx.fleet) {
        repair_fleet(ctx, routes, std::min(1.0, totalBudget * 0.15));
        if ((int)routes.size() > ctx.fleet) {
            Sol ff = bfd_init(ctx);
            if ((int)ff.size() <= ctx.fleet) routes = ff;
        }
    }
    granular_polish(ctx, mut, routes, std::max(0.05, totalBudget * 0.12), seed, penalty0);

    // ALNS
    double alnsTime = std::max(0.0, deadline - now_s() - 0.01);
    Sol improved = alns(ctx, mut, routes, alnsTime, seed, penalty0, use_penalty);

    Sol* finalSol = &improved;
    bool fImp = feasible(ctx, improved), fInit = feasible(ctx, routes);
    long long cImp = total_dist(ctx, improved), cInit = total_dist(ctx, routes);
    if ((fInit && !fImp) || (fInit == fImp && cInit < cImp)) finalSol = &routes;

    int pos = 0;
    for (const auto& r : *finalSol) {
        if (r.empty()) continue;
        for (int v : r) {
            if (pos >= out_cap - 2) return 1;
            out_flat[pos++] = v;
        }
        out_flat[pos++] = -1;
    }
    out_flat[pos++] = -2;
    out_info[0] = pos;
    out_info[1] = g_iterations;
    out_info[2] = ctx.evals;
    out_info[3] = total_dist(ctx, *finalSol);
    out_info[4] = feasible(ctx, *finalSol) ? 1 : 0;
    return 0;
}


int senda_solve_ex(
    int n_nodes,
    const double* xs, const double* ys,
    const int32_t* dist,
    const int32_t* demands,
    int capacity, int depot, int vehicle_hint,
    const int32_t* customer_ids, int n_customers,
    const int32_t* init_flat, int init_len,
    double time_limit_sec, uint64_t seed, int k,
    int use_segment_moves, int use_penalty,
    int budget_mode, int64_t alns_iterations, int polish_mode,
    int exchange_max_passes, int best_polish_max_calls,
    double destroy_min, double destroy_max,
    double cand_ls_budget, double best_polish_budget,
    int32_t* out_flat, int out_cap,
    int64_t* out_info /* [0]=len [1]=iters [2]=evals [3]=dist [4]=feasible */) {

    double started = now_s();
    RunOpts opts;
    opts.budgetMode = budget_mode;
    opts.alnsIterations = alns_iterations;
    opts.polishMode = polish_mode;
    opts.exchangeMaxPasses = exchange_max_passes;
    opts.bestPolishMaxCalls = best_polish_max_calls;
    if (destroy_min >= 0.0 && destroy_max > destroy_min) {
        opts.destroyMin = destroy_min;
        opts.destroyMax = destroy_max;
    }
    opts.candLsBudget = cand_ls_budget;
    opts.bestPolishBudget = best_polish_budget;

    Ctx ctx;
    ctx.n = n_nodes;
    ctx.dem.assign(demands, demands + n_nodes);
    ctx.cap = capacity;
    ctx.depot = depot;
    ctx.fleet = vehicle_hint;
    ctx.useSegment = (use_segment_moves & 1) != 0;
    ctx.useExchangeReinsert = (use_segment_moves & 2) != 0;
    ctx.customers.assign(customer_ids, customer_ids + n_customers);

    if (dist != nullptr) {
        ctx.D = dist;
        ctx.symmetric = true;
        for (int a : ctx.customers) {
            for (int b : ctx.customers) if (b > a && ctx.d(a, b) != ctx.d(b, a)) {
                ctx.symmetric = false; break;
            }
            if (!ctx.symmetric) break;
        }
    } else {
        // build rounded-euclidean matrix in C++ (CVRPLIB convention)
        ctx.Dstore.assign((size_t)n_nodes * n_nodes, 0);
        vector<int> ids = ctx.customers;
        ids.push_back(depot);
        for (int a : ids) {
            for (int b : ids) {
                if (a == b) continue;
                double dx = xs[a] - xs[b], dy = ys[a] - ys[b];
                ctx.Dstore[(size_t)a * n_nodes + b] =
                    (int32_t)(std::sqrt(dx * dx + dy * dy) + 0.5);
            }
        }
        ctx.D = ctx.Dstore.data();
        ctx.symmetric = true;
    }

    // neighbor lists
    int nc = (int)ctx.customers.size();
    int kEff = (nc <= 60) ? std::max(1, nc - 1) : k;
    ctx.nbr.assign(ctx.n, {});
    for (int u : ctx.customers) {
        vector<int> others;
        for (int v : ctx.customers) if (v != u) others.push_back(v);
        std::sort(others.begin(), others.end(),
                  [&](int a, int b) { return ctx.d(u, a) < ctx.d(u, b); });
        if ((int)others.size() > kEff) others.resize(kEff);
        ctx.nbr[u] = others;
    }

    // base penalty, scaled by max distance / max demand
    int maxDist = 0, maxDem = 1;
    for (int u : ctx.customers) {
        maxDem = std::max(maxDem, ctx.dem[u]);
        maxDist = std::max(maxDist, ctx.d(ctx.depot, u));
    }
    double penalty0 = std::max(0.5, std::min(1000.0, (double)maxDist / (double)maxDem));

    double totalBudget = (opts.budgetMode == 1) ? 1.0e9 : time_limit_sec;
    double deadline = started + totalBudget;
    Ctx& mut = ctx;

    // init
    Sol routes;
    if (init_len > 0) {
        vector<int> cur;
        for (int i = 0; i < init_len; ++i) {
            int v = init_flat[i];
            if (v == -2) break;
            if (v == -1) { if (!cur.empty()) routes.push_back(cur); cur.clear(); }
            else cur.push_back(v);
        }
        if (!cur.empty()) routes.push_back(cur);
    } else {
        routes = (ctx.fleet > 0) ? bfd_init(ctx) : nn_init(ctx);
    }
    if (ctx.fleet >= 0 && (int)routes.size() > ctx.fleet) {
        repair_fleet(ctx, routes, std::min(1.0, totalBudget * 0.15));
        if ((int)routes.size() > ctx.fleet) {
            Sol ff = bfd_init(ctx);
            if ((int)ff.size() <= ctx.fleet) routes = ff;
        }
    }
    double initPolishLimit = (opts.budgetMode == 1)
        ? std::max(0.0, opts.bestPolishBudget)
        : std::max(0.05, totalBudget * 0.12);
    granular_polish(ctx, mut, routes, initPolishLimit, seed, penalty0, opts.exchangeMaxPasses);

    // ALNS
    double alnsTime = (opts.budgetMode == 1)
        ? (double)std::max<int64_t>(1, opts.alnsIterations)
        : std::max(0.0, deadline - now_s() - 0.01);
    Sol improved = alns(ctx, mut, routes, alnsTime, seed, penalty0, use_penalty, opts);

    Sol* finalSol = &improved;
    bool fImp = feasible(ctx, improved), fInit = feasible(ctx, routes);
    long long cImp = total_dist(ctx, improved), cInit = total_dist(ctx, routes);
    if ((fInit && !fImp) || (fInit == fImp && cInit < cImp)) finalSol = &routes;

    int pos = 0;
    for (const auto& r : *finalSol) {
        if (r.empty()) continue;
        for (int v : r) {
            if (pos >= out_cap - 2) return 1;
            out_flat[pos++] = v;
        }
        out_flat[pos++] = -1;
    }
    out_flat[pos++] = -2;
    out_info[0] = pos;
    out_info[1] = g_iterations;
    out_info[2] = ctx.evals;
    out_info[3] = total_dist(ctx, *finalSol);
    out_info[4] = feasible(ctx, *finalSol) ? 1 : 0;
    return 0;
}


static int solve2_multi_impl(
    int n_nodes,
    const double* xs, const double* ys,
    const int32_t* dist,
    const int32_t* demands,
    int capacity, int depot, int vehicle_hint,
    const int32_t* customer_ids, int n_customers,
    const int32_t* init_flat, int init_len,
    const uint64_t* seeds, int n_seeds,
    const int32_t* cfg_k,
    const int32_t* cfg_use_segment_moves,
    const int32_t* cfg_use_penalty,
    const int32_t* cfg_budget_mode,
    const int64_t* cfg_alns_iterations,
    const int32_t* cfg_polish_mode,
    const int32_t* cfg_exchange_max_passes,
    const int32_t* cfg_best_polish_max_calls,
    const double* cfg_destroy_min,
    const double* cfg_destroy_max,
    const double* cfg_cand_ls_budget,
    const double* cfg_best_polish_budget,
    const int64_t* cfg_stagnation_iters,  // nullptr or per-config early-stop limit (0 = off)
    int warm_start,                       // 1: runs after the first start from incumbent best
    int n_configs,
    double time_limit_sec,
    int32_t* out_flat, int out_cap,
    int64_t* out_info /* [0]=len [1]=iters [2]=evals [3]=dist [4]=feasible [5]=cfg [6]=seed [7]=runs [8]=ms [9]=routes */) {

    if (n_configs <= 0 || n_seeds <= 0) return 2;
    double started = now_s();

    Ctx ctx;
    ctx.n = n_nodes;
    ctx.dem.assign(demands, demands + n_nodes);
    ctx.cap = capacity;
    ctx.depot = depot;
    ctx.fleet = vehicle_hint;
    ctx.customers.assign(customer_ids, customer_ids + n_customers);

    if (dist != nullptr) {
        ctx.D = dist;
        ctx.symmetric = true;
        for (int a : ctx.customers) {
            for (int b : ctx.customers) if (b > a && ctx.d(a, b) != ctx.d(b, a)) {
                ctx.symmetric = false; break;
            }
            if (!ctx.symmetric) break;
        }
    } else {
        ctx.Dstore.assign((size_t)n_nodes * n_nodes, 0);
        vector<int> ids = ctx.customers;
        ids.push_back(depot);
        for (int a : ids) {
            for (int b : ids) {
                if (a == b) continue;
                double dx = xs[a] - xs[b], dy = ys[a] - ys[b];
                ctx.Dstore[(size_t)a * n_nodes + b] =
                    (int32_t)(std::sqrt(dx * dx + dy * dy) + 0.5);
            }
        }
        ctx.D = ctx.Dstore.data();
        ctx.symmetric = true;
    }

    double penalty0 = base_penalty(ctx);
    Sol baseRoutes = initial_routes(ctx, init_flat, init_len);
    if (ctx.fleet >= 0 && (int)baseRoutes.size() > ctx.fleet) {
        repair_fleet(ctx, baseRoutes, 1.0);
        if ((int)baseRoutes.size() > ctx.fleet) {
            Sol ff = bfd_init(ctx);
            if ((int)ff.size() <= ctx.fleet) baseRoutes = ff;
        }
    }

    Sol bestSol;
    long long bestDist = 0;
    bool bestFeas = false;
    bool haveBest = false;
    int bestCfg = -1, bestSeed = -1;
    long long totalIterations = 0;
    long long runs = 0;

    auto makeOpts = [&](int ci) {
        RunOpts opts;
        opts.budgetMode = cfg_budget_mode ? cfg_budget_mode[ci] : 1;
        opts.alnsIterations = cfg_alns_iterations ? cfg_alns_iterations[ci] : 5000;
        opts.polishMode = cfg_polish_mode ? cfg_polish_mode[ci] : 3;
        opts.exchangeMaxPasses = cfg_exchange_max_passes ? cfg_exchange_max_passes[ci] : 2;
        opts.bestPolishMaxCalls = cfg_best_polish_max_calls ? cfg_best_polish_max_calls[ci] : 50;
        if (cfg_destroy_min && cfg_destroy_max && cfg_destroy_min[ci] >= 0.0 && cfg_destroy_max[ci] > cfg_destroy_min[ci]) {
            opts.destroyMin = cfg_destroy_min[ci];
            opts.destroyMax = cfg_destroy_max[ci];
        }
        opts.candLsBudget = cfg_cand_ls_budget ? cfg_cand_ls_budget[ci] : 0.08;
        opts.bestPolishBudget = cfg_best_polish_budget ? cfg_best_polish_budget[ci] : 0.15;
        if (cfg_stagnation_iters && cfg_stagnation_iters[ci] > 0)
            opts.stagnationLimit = cfg_stagnation_iters[ci];
        return opts;
    };
    auto setMoves = [&](int ci) {
        ctx.useSegment = cfg_use_segment_moves ? ((cfg_use_segment_moves[ci] & 1) != 0) : true;
        ctx.useExchangeReinsert = cfg_use_segment_moves ? ((cfg_use_segment_moves[ci] & 2) != 0) : true;
        ctx.useOrOpt3 = cfg_use_segment_moves ? ((cfg_use_segment_moves[ci] & 4) != 0) : false;
        build_neighbors(ctx, cfg_k ? cfg_k[ci] : 15);
    };

    for (int ci = 0; ci < n_configs; ++ci) {
        RunOpts opts = makeOpts(ci);
        setMoves(ci);

        for (int si = 0; si < n_seeds; ++si) {
            uint64_t seed = seeds[si];
            bool warm = warm_start == 1 && haveBest && bestFeas && runs > 0;
            Sol routes = warm ? bestSol : baseRoutes;
            RunOpts optsRun = opts;
            if (warm) optsRun.t0Scale = 0.35;  // gentler restart around the incumbent
            Ctx& mut = ctx;
            if (!warm) {
                double initPolishLimit = (opts.budgetMode == 1)
                    ? std::max(0.0, opts.bestPolishBudget)
                    : std::max(0.05, time_limit_sec * 0.12);
                granular_polish(ctx, mut, routes, initPolishLimit, seed, penalty0, opts.exchangeMaxPasses);
            }

            double alnsTime = (optsRun.budgetMode == 1)
                ? (double)std::max<int64_t>(1, optsRun.alnsIterations)
                : std::max(0.0, time_limit_sec);
            Sol improved = alns(ctx, mut, routes, alnsTime, seed, penalty0,
                                cfg_use_penalty ? cfg_use_penalty[ci] : 0, optsRun);
            totalIterations += g_iterations;
            ++runs;

            Sol* finalSol = &improved;
            bool fImp = feasible(ctx, improved), fInit = feasible(ctx, routes);
            long long cImp = total_dist(ctx, improved), cInit = total_dist(ctx, routes);
            if ((fInit && !fImp) || (fInit == fImp && cInit < cImp)) finalSol = &routes;

            bool f = feasible(ctx, *finalSol);
            long long c = total_dist(ctx, *finalSol);
            if (!haveBest || (f && !bestFeas) || (f == bestFeas && c < bestDist)) {
                bestSol = *finalSol;
                bestDist = c;
                bestFeas = f;
                bestCfg = ci;
                bestSeed = si;
                haveBest = true;
            }
        }
    }

    // warm_start == 2: reinvest iterations saved by early stopping into extra
    // cold restarts of the incumbent's config, then a final polish of the best.
    if (warm_start == 2 && haveBest && bestFeas) {
        long long scheduled = 0;
        for (int ci = 0; ci < n_configs; ++ci)
            scheduled += (long long)n_seeds * (cfg_alns_iterations ? cfg_alns_iterations[ci] : 5000);
        long long leftover = scheduled - totalIterations;
        int extra = 0;
        Ctx& mut = ctx;
        while (extra < 24) {
            int ci = bestCfg < 0 ? 0 : bestCfg;
            long long nominal = cfg_alns_iterations ? cfg_alns_iterations[ci] : 5000;
            if (leftover < nominal / 2) break;
            RunOpts opts = makeOpts(ci);
            setMoves(ci);
            uint64_t seed = seeds[extra % n_seeds] ^ (0x9E3779B97F4A7C15ULL * (uint64_t)(extra + 1));
            Sol routes = baseRoutes;
            granular_polish(ctx, mut, routes, std::max(0.0, opts.bestPolishBudget), seed,
                            penalty0, opts.exchangeMaxPasses);
            double alnsTime = (opts.budgetMode == 1)
                ? (double)std::max<int64_t>(1, opts.alnsIterations)
                : std::max(0.0, time_limit_sec);
            Sol improved = alns(ctx, mut, routes, alnsTime, seed, penalty0,
                                cfg_use_penalty ? cfg_use_penalty[ci] : 0, opts);
            totalIterations += g_iterations;
            leftover -= g_iterations;
            ++runs;
            ++extra;

            Sol* finalSol = &improved;
            bool fImp = feasible(ctx, improved), fInit = feasible(ctx, routes);
            long long cImp = total_dist(ctx, improved), cInit = total_dist(ctx, routes);
            if ((fInit && !fImp) || (fInit == fImp && cInit < cImp)) finalSol = &routes;
            bool f = feasible(ctx, *finalSol);
            long long c = total_dist(ctx, *finalSol);
            if ((f && !bestFeas) || (f == bestFeas && c < bestDist)) {
                bestSol = *finalSol;
                bestDist = c;
                bestFeas = f;
                bestCfg = ci;
            }
        }
        // final intensification of the incumbent
        setMoves(bestCfg < 0 ? 0 : bestCfg);
        Sol pol = bestSol;
        granular_polish(ctx, mut, pol, 0.5, seeds[0], penalty0, -1);
        long long pd = total_dist(ctx, pol);
        if (feasible(ctx, pol) && pd < bestDist) { bestSol = pol; bestDist = pd; }
    }

    if (!haveBest) return 3;
    int pos = emit_solution(ctx, bestSol, out_flat, out_cap);
    if (pos < 0) return 1;
    out_info[0] = pos;
    out_info[1] = totalIterations;
    out_info[2] = ctx.evals;
    out_info[3] = bestDist;
    out_info[4] = bestFeas ? 1 : 0;
    out_info[5] = bestCfg;
    out_info[6] = bestSeed;
    out_info[7] = runs;
    out_info[8] = (int64_t)((now_s() - started) * 1000.0);
    out_info[9] = (int64_t)bestSol.size();
    return 0;
}

int senda_solve_multi(
    int n_nodes,
    const double* xs, const double* ys,
    const int32_t* dist,
    const int32_t* demands,
    int capacity, int depot, int vehicle_hint,
    const int32_t* customer_ids, int n_customers,
    const int32_t* init_flat, int init_len,
    const uint64_t* seeds, int n_seeds,
    const int32_t* cfg_k,
    const int32_t* cfg_use_segment_moves,
    const int32_t* cfg_use_penalty,
    const int32_t* cfg_budget_mode,
    const int64_t* cfg_alns_iterations,
    const int32_t* cfg_polish_mode,
    const int32_t* cfg_exchange_max_passes,
    const int32_t* cfg_best_polish_max_calls,
    const double* cfg_destroy_min,
    const double* cfg_destroy_max,
    const double* cfg_cand_ls_budget,
    const double* cfg_best_polish_budget,
    int n_configs,
    double time_limit_sec,
    int32_t* out_flat, int out_cap,
    int64_t* out_info) {
    return solve2_multi_impl(
        n_nodes, xs, ys, dist, demands, capacity, depot, vehicle_hint,
        customer_ids, n_customers, init_flat, init_len, seeds, n_seeds,
        cfg_k, cfg_use_segment_moves, cfg_use_penalty, cfg_budget_mode,
        cfg_alns_iterations, cfg_polish_mode, cfg_exchange_max_passes,
        cfg_best_polish_max_calls, cfg_destroy_min, cfg_destroy_max,
        cfg_cand_ls_budget, cfg_best_polish_budget,
        nullptr, 0,
        n_configs, time_limit_sec, out_flat, out_cap, out_info);
}

// Early-stop + warm-start variant. Additive ABI: senda_solve_multi is untouched.
int senda_solve_multi_es(
    int n_nodes,
    const double* xs, const double* ys,
    const int32_t* dist,
    const int32_t* demands,
    int capacity, int depot, int vehicle_hint,
    const int32_t* customer_ids, int n_customers,
    const int32_t* init_flat, int init_len,
    const uint64_t* seeds, int n_seeds,
    const int32_t* cfg_k,
    const int32_t* cfg_use_segment_moves,
    const int32_t* cfg_use_penalty,
    const int32_t* cfg_budget_mode,
    const int64_t* cfg_alns_iterations,
    const int32_t* cfg_polish_mode,
    const int32_t* cfg_exchange_max_passes,
    const int32_t* cfg_best_polish_max_calls,
    const double* cfg_destroy_min,
    const double* cfg_destroy_max,
    const double* cfg_cand_ls_budget,
    const double* cfg_best_polish_budget,
    const int64_t* cfg_stagnation_iters,
    int warm_start,
    int n_configs,
    double time_limit_sec,
    int32_t* out_flat, int out_cap,
    int64_t* out_info) {
    return solve2_multi_impl(
        n_nodes, xs, ys, dist, demands, capacity, depot, vehicle_hint,
        customer_ids, n_customers, init_flat, init_len, seeds, n_seeds,
        cfg_k, cfg_use_segment_moves, cfg_use_penalty, cfg_budget_mode,
        cfg_alns_iterations, cfg_polish_mode, cfg_exchange_max_passes,
        cfg_best_polish_max_calls, cfg_destroy_min, cfg_destroy_max,
        cfg_cand_ls_budget, cfg_best_polish_budget,
        cfg_stagnation_iters, warm_start,
        n_configs, time_limit_sec, out_flat, out_cap, out_info);
}

// Parallel variant: runs the (config x seed) grid on n_threads worker threads.
// Runs are cold and independent; results are reduced deterministically by job
// index, so the output is identical for any thread count (including 1).
// warm_start semantics are not supported here (sequential by nature).
int senda_solve_multi_par(
    int n_nodes,
    const double* xs, const double* ys,
    const int32_t* dist,
    const int32_t* demands,
    int capacity, int depot, int vehicle_hint,
    const int32_t* customer_ids, int n_customers,
    const int32_t* init_flat, int init_len,
    const uint64_t* seeds, int n_seeds,
    const int32_t* cfg_k,
    const int32_t* cfg_use_segment_moves,
    const int32_t* cfg_use_penalty,
    const int32_t* cfg_budget_mode,
    const int64_t* cfg_alns_iterations,
    const int32_t* cfg_polish_mode,
    const int32_t* cfg_exchange_max_passes,
    const int32_t* cfg_best_polish_max_calls,
    const double* cfg_destroy_min,
    const double* cfg_destroy_max,
    const double* cfg_cand_ls_budget,
    const double* cfg_best_polish_budget,
    const int64_t* cfg_stagnation_iters,
    int n_threads,
    int n_configs,
    double time_limit_sec,
    int32_t* out_flat, int out_cap,
    int64_t* out_info) {

    if (n_configs <= 0 || n_seeds <= 0) return 2;
    double started = now_s();

    Ctx base;
    base.n = n_nodes;
    base.dem.assign(demands, demands + n_nodes);
    base.cap = capacity;
    base.depot = depot;
    base.fleet = vehicle_hint;
    base.customers.assign(customer_ids, customer_ids + n_customers);

    if (dist != nullptr) {
        base.D = dist;
        base.symmetric = true;
        for (int a : base.customers) {
            for (int b : base.customers) if (b > a && base.d(a, b) != base.d(b, a)) {
                base.symmetric = false; break;
            }
            if (!base.symmetric) break;
        }
    } else {
        base.Dstore.assign((size_t)n_nodes * n_nodes, 0);
        vector<int> ids = base.customers;
        ids.push_back(depot);
        for (int a : ids) {
            for (int b : ids) {
                if (a == b) continue;
                double dx = xs[a] - xs[b], dy = ys[a] - ys[b];
                base.Dstore[(size_t)a * n_nodes + b] =
                    (int32_t)(std::sqrt(dx * dx + dy * dy) + 0.5);
            }
        }
        base.D = base.Dstore.data();
        base.symmetric = true;
    }

    double penalty0 = base_penalty(base);
    Sol baseRoutes = initial_routes(base, init_flat, init_len);
    if (base.fleet >= 0 && (int)baseRoutes.size() > base.fleet) {
        repair_fleet(base, baseRoutes, 1.0);
        if ((int)baseRoutes.size() > base.fleet) {
            Sol ff = bfd_init(base);
            if ((int)ff.size() <= base.fleet) baseRoutes = ff;
        }
    }

    // per-config options and neighbor lists (read-only during the runs)
    vector<RunOpts> cfgOpts(n_configs);
    vector<vector<vector<int>>> cfgNbr(n_configs);
    for (int ci = 0; ci < n_configs; ++ci) {
        RunOpts opts;
        opts.budgetMode = cfg_budget_mode ? cfg_budget_mode[ci] : 1;
        opts.alnsIterations = cfg_alns_iterations ? cfg_alns_iterations[ci] : 5000;
        opts.polishMode = cfg_polish_mode ? cfg_polish_mode[ci] : 3;
        opts.exchangeMaxPasses = cfg_exchange_max_passes ? cfg_exchange_max_passes[ci] : 2;
        opts.bestPolishMaxCalls = cfg_best_polish_max_calls ? cfg_best_polish_max_calls[ci] : 50;
        if (cfg_destroy_min && cfg_destroy_max && cfg_destroy_min[ci] >= 0.0 && cfg_destroy_max[ci] > cfg_destroy_min[ci]) {
            opts.destroyMin = cfg_destroy_min[ci];
            opts.destroyMax = cfg_destroy_max[ci];
        }
        opts.candLsBudget = cfg_cand_ls_budget ? cfg_cand_ls_budget[ci] : 0.08;
        opts.bestPolishBudget = cfg_best_polish_budget ? cfg_best_polish_budget[ci] : 0.15;
        if (cfg_stagnation_iters && cfg_stagnation_iters[ci] > 0)
            opts.stagnationLimit = cfg_stagnation_iters[ci];
        cfgOpts[ci] = opts;
        Ctx tmp = base;
        tmp.Dstore.clear();
        tmp.D = base.D;
        build_neighbors(tmp, cfg_k ? cfg_k[ci] : 15);
        cfgNbr[ci] = std::move(tmp.nbr);
    }

    struct RunResult {
        Sol sol;
        long long dist = 0;
        bool feas = false;
        long long iters = 0;
        long long evals = 0;
    };
    int jobs = n_configs * n_seeds;
    vector<RunResult> res(jobs);
    std::atomic<int> cursor{0};

    auto work = [&]() {
        Ctx tctx = base;
        tctx.Dstore.clear();
        tctx.Dstore.shrink_to_fit();
        tctx.D = base.D;
        for (;;) {
            int j = cursor.fetch_add(1);
            if (j >= jobs) break;
            int ci = j / n_seeds, si = j % n_seeds;
            const RunOpts& opts = cfgOpts[ci];
            tctx.useSegment = cfg_use_segment_moves ? ((cfg_use_segment_moves[ci] & 1) != 0) : true;
            tctx.useExchangeReinsert = cfg_use_segment_moves ? ((cfg_use_segment_moves[ci] & 2) != 0) : true;
            tctx.useOrOpt3 = cfg_use_segment_moves ? ((cfg_use_segment_moves[ci] & 4) != 0) : false;
            tctx.nbr = cfgNbr[ci];
            tctx.evals = 0;
            uint64_t seed = seeds[si];

            Sol routes = baseRoutes;
            double initPolishLimit = (opts.budgetMode == 1)
                ? std::max(0.0, opts.bestPolishBudget)
                : std::max(0.05, time_limit_sec * 0.12);
            granular_polish(tctx, tctx, routes, initPolishLimit, seed, penalty0, opts.exchangeMaxPasses);
            // NO_ALNS must remain a valid solver ablation: when the penalized
            // initial polish crosses capacity, fall back to the pristine
            // feasible construction rather than emitting an infeasible route.
            if (opts.alnsIterations < 0 && !feasible(tctx, routes))
                routes = baseRoutes;

            double alnsTime = (opts.budgetMode == 1)
                ? (double)std::max<int64_t>(1, opts.alnsIterations)
                : std::max(0.0, time_limit_sec);
            Sol improved = alns(tctx, tctx, routes, alnsTime, seed, penalty0,
                                cfg_use_penalty ? cfg_use_penalty[ci] : 0, opts);

            Sol* finalSol = &improved;
            bool fImp = feasible(tctx, improved), fInit = feasible(tctx, routes);
            long long cImp = total_dist(tctx, improved), cInit = total_dist(tctx, routes);
            if ((fInit && !fImp) || (fInit == fImp && cInit < cImp)) finalSol = &routes;

            res[j].sol = *finalSol;
            res[j].dist = total_dist(tctx, *finalSol);
            res[j].feas = feasible(tctx, *finalSol);
            res[j].iters = g_iterations;
            res[j].evals = tctx.evals;
        }
    };

    int nt = std::max(1, n_threads);
    if (nt > jobs) nt = jobs;
    vector<std::thread> pool;
    for (int t = 1; t < nt; ++t) pool.emplace_back(work);
    work();
    for (auto& th : pool) th.join();

    // deterministic reduction by job index
    long long totalIterations = 0, totalEvals = 0;
    int bestJob = -1;
    for (int j = 0; j < jobs; ++j) {
        totalIterations += res[j].iters;
        totalEvals += res[j].evals;
        if (bestJob < 0 ||
            (res[j].feas && !res[bestJob].feas) ||
            (res[j].feas == res[bestJob].feas && res[j].dist < res[bestJob].dist))
            bestJob = j;
    }
    if (bestJob < 0) return 3;
    const RunResult& best = res[bestJob];

    int pos = emit_solution(base, best.sol, out_flat, out_cap);
    if (pos < 0) return 1;
    out_info[0] = pos;
    out_info[1] = totalIterations;
    out_info[2] = totalEvals;
    out_info[3] = best.dist;
    out_info[4] = best.feas ? 1 : 0;
    out_info[5] = bestJob / n_seeds;
    out_info[6] = bestJob % n_seeds;
    out_info[7] = jobs;
    out_info[8] = (int64_t)((now_s() - started) * 1000.0);
    out_info[9] = (int64_t)best.sol.size();
    return 0;
}

} // extern "C"

