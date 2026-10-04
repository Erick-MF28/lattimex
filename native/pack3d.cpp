// pack3d.cpp — empacador 3D de puntos extremos, traducción 1:1 a C++ del empacador en Python
// de este mismo repositorio (lattimex/engine/loading3d.py), escrito por el mismo autor.
// La idea de puntos extremos proviene de Crainic, Perboli y Tadei (2008); ver docs/ACADEMIC_NOTES.md.
// Generador pseudoaleatorio: adaptación de Mulberry32 (Tommy Ettinger, CC0-1.0).
// Original: https://gist.github.com/tommyettinger/46a874533244883189143505d203312c
// Dedicación al dominio público: https://creativecommons.org/publicdomain/zero/1.0/
//
// Replica exactamente ExtremePoint3D._pack_attempt / _ordered / _verify y el
// bucle de reinicios de evaluate(): mismo PRNG (Mulberry32), mismos ordenes
// estables, mismos umbrales EPS y mismas formulas de score en el mismo orden
// de operaciones, de modo que produce las MISMAS colocaciones que Python.
// La verificacion final y el asentado por gravedad siguen en Python.
//
// Compilar: g++ -std=c++17 -O3 -shared -fPIC -o liblattimex_pack3d.so pack3d.cpp
#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <set>
#include <tuple>
#include <vector>

namespace {

constexpr double EPS = 1e-7;

struct Mulberry32 {
    uint32_t state;
    explicit Mulberry32(uint32_t seed) : state(seed) {}
    double random() {
        state += 0x6D2B79F5u;
        uint32_t v = state;
        v = (v ^ (v >> 15)) * (v | 1u);
        v ^= v + ((v ^ (v >> 7)) * (v | 61u));
        return (double)(v ^ (v >> 14)) / 4294967296.0;
    }
};

struct Rot { double d[3]; int code; };

struct Item {
    int index;              // posicion en el request
    double dims[3];         // originales
    std::vector<Rot> rot;
    double volume, weight, difficulty;
    int rank;
    bool fragile, stackable;
};

struct Box {
    int item;               // indice de Item
    double x, y, z, l, w, h;
    int rank, orient;
    bool fragile, stackable;
};

inline bool overlap1(double a0, double a1, double b0, double b1) {
    return std::min(a1, b1) - std::max(a0, b0) > EPS;
}
inline bool boxes_overlap(const Box& a, const Box& b) {
    return overlap1(a.x, a.x + a.l, b.x, b.x + b.l) && overlap1(a.y, a.y + a.w, b.y, b.y + b.w)
        && overlap1(a.z, a.z + a.h, b.z, b.z + b.h);
}
inline bool yz_overlap(const Box& a, const Box& b) {
    return overlap1(a.y, a.y + a.w, b.y, b.y + b.w) && overlap1(a.z, a.z + a.h, b.z, b.z + b.h);
}

struct Rect { double x0, x1, y0, y1; const Box* box; };

inline bool clipped_support(const Box& box, const Box& item, Rect& out) {
    if (std::fabs(box.z + box.h - item.z) > EPS) return false;
    double x0 = std::max(box.x, item.x), x1 = std::min(box.x + box.l, item.x + item.l);
    double y0 = std::max(box.y, item.y), y1 = std::min(box.y + box.w, item.y + item.w);
    if (x1 - x0 <= EPS || y1 - y0 <= EPS) return false;
    out = {x0, x1, y0, y1, &box};
    return true;
}

double union_area(const std::vector<Rect>& rs) {
    if (rs.empty()) return 0.0;
    std::vector<double> xs;
    for (const auto& r : rs) { xs.push_back(r.x0); xs.push_back(r.x1); }
    std::sort(xs.begin(), xs.end());
    xs.erase(std::unique(xs.begin(), xs.end()), xs.end());
    double area = 0.0;
    std::vector<std::pair<double, double>> iv;
    for (size_t i = 0; i + 1 < xs.size(); ++i) {
        double left = xs[i], right = xs[i + 1];
        if (right - left <= EPS) continue;
        iv.clear();
        for (const auto& r : rs)
            if (r.x0 < right - EPS && r.x1 > left + EPS) iv.push_back({r.y0, r.y1});
        if (iv.empty()) continue;
        std::sort(iv.begin(), iv.end());
        double start = iv[0].first, end = iv[0].second, covered = 0.0;
        for (size_t k = 1; k < iv.size(); ++k) {
            if (iv[k].first <= end + EPS) end = std::max(end, iv[k].second);
            else { covered += end - start; start = iv[k].first; end = iv[k].second; }
        }
        covered += end - start;
        area += (right - left) * covered;
    }
    return area;
}

struct Support { double ratio; std::vector<const Box*> boxes; };

// `self` puede ser nullptr (candidato) o apuntar al propio box (verificacion).
Support support_info(const Box& item, const std::vector<Box>& placed, const Box* self) {
    Support s;
    if (item.z <= EPS) { s.ratio = 1.0; return s; }
    std::vector<Rect> rs;
    for (const auto& b : placed) {
        if (&b == self) continue;
        Rect r;
        if (clipped_support(b, item, r)) rs.push_back(r);
    }
    s.ratio = union_area(rs) / (item.l * item.w);
    for (const auto& r : rs) s.boxes.push_back(r.box);
    return s;
}

inline bool inside_cargo(const Box& b, const double* c) {
    return b.x >= -EPS && b.y >= -EPS && b.z >= -EPS && b.x + b.l <= c[0] + EPS
        && b.y + b.w <= c[1] + EPS && b.z + b.h <= c[2] + EPS;
}

bool sequence_compatible(const Box& cand, const std::vector<Box>& placed, const Box* self) {
    for (const auto& b : placed) {
        if (&b == self) continue;
        if (cand.rank == b.rank || !yz_overlap(cand, b)) continue;
        if (cand.rank < b.rank) { if (cand.x < b.x + b.l - EPS) return false; }
        else if (cand.x + cand.l > b.x + EPS) return false;
    }
    return true;
}

int contact_score(const Box& c, const std::vector<Box>& placed, const double* cargo) {
    int s = 0;
    s += (c.x <= EPS || c.x + c.l >= cargo[0] - EPS);
    s += (c.y <= EPS || c.y + c.w >= cargo[1] - EPS);
    s += (c.z <= EPS || c.z + c.h >= cargo[2] - EPS);
    for (const auto& b : placed) {
        s += (std::fabs(c.x - (b.x + b.l)) <= EPS || std::fabs(c.x + c.l - b.x) <= EPS);
        s += (std::fabs(c.y - (b.y + b.w)) <= EPS || std::fabs(c.y + c.w - b.y) <= EPS);
        s += (std::fabs(c.z - (b.z + b.h)) <= EPS || std::fabs(c.z + c.h - b.z) <= EPS);
    }
    return s;
}

using Pt = std::array<double, 3>;
using Key = std::tuple<double, double, double>;
inline double r3(double v) { return std::nearbyint(v * 1000.0) / 1000.0; }
inline Key key_of(const Pt& p) { return {r3(p[0]), r3(p[1]), r3(p[2])}; }

void candidate_positions(const std::vector<Pt>& points, const double* d, const double* cargo,
                         std::vector<Pt>& out) {
    out.clear();
    std::set<Key> seen;
    for (const auto& b : points) {
        const Pt raws[7] = {
            {b[0], b[1], b[2]}, {cargo[0] - d[0], b[1], b[2]},
            {b[0], 0.0, b[2]}, {b[0], cargo[1] - d[1], b[2]},
            {b[0], b[1], 0.0}, {cargo[0] - d[0], 0.0, b[2]},
            {cargo[0] - d[0], cargo[1] - d[1], b[2]},
        };
        for (const auto& raw : raws) {
            if (std::min({raw[0], raw[1], raw[2]}) < -EPS) continue;
            Pt p = {std::max(0.0, raw[0]), std::max(0.0, raw[1]), std::max(0.0, raw[2])};
            if (seen.insert(key_of(p)).second) out.push_back(p);
        }
    }
}

void prune_points(std::vector<Pt>& points, const std::vector<Box>& placed, const double* cargo) {
    std::vector<Pt> res;
    std::set<Key> seen;
    for (const auto& p : points) {
        if (std::min({p[0], p[1], p[2]}) < -EPS || p[0] > cargo[0] + EPS || p[1] > cargo[1] + EPS
            || p[2] > cargo[2] + EPS) continue;
        bool inside = false;
        for (const auto& b : placed) {
            if (p[0] > b.x + EPS && p[0] < b.x + b.l - EPS && p[1] > b.y + EPS && p[1] < b.y + b.w - EPS
                && p[2] > b.z + EPS && p[2] < b.z + b.h - EPS) { inside = true; break; }
        }
        if (!inside && seen.insert(key_of(p)).second) res.push_back(p);
    }
    points.swap(res);
}

struct Opts { double support_ratio; bool unload_order, fragility; };

// Orden de un intento: replica _ordered (sort estable por clave; attempt>=6
// aplica una segunda ordenacion con clave aleatoria calculada en el orden actual).
std::vector<int> ordered(const std::vector<Item>& items, int attempt, Mulberry32& rng) {
    std::vector<int> idx(items.size());
    for (size_t i = 0; i < idx.size(); ++i) idx[i] = (int)i;
    int variant = attempt % 6;
    auto face = [](const Item& it) {
        return std::max({it.dims[0] * it.dims[1], it.dims[0] * it.dims[2], it.dims[1] * it.dims[2]});
    };
    auto mx = [](const Item& it) { return std::max({it.dims[0], it.dims[1], it.dims[2]}); };
    switch (variant) {
    case 0: std::stable_sort(idx.begin(), idx.end(), [&](int a, int b) {
                return std::make_pair(-items[a].difficulty, -items[a].volume)
                     < std::make_pair(-items[b].difficulty, -items[b].volume); }); break;
    case 1: std::stable_sort(idx.begin(), idx.end(), [&](int a, int b) {
                return -items[a].volume < -items[b].volume; }); break;
    case 2: std::stable_sort(idx.begin(), idx.end(), [&](int a, int b) {
                return -mx(items[a]) < -mx(items[b]); }); break;
    case 3: std::stable_sort(idx.begin(), idx.end(), [&](int a, int b) {
                return std::make_pair(-(double)items[a].rank, -items[a].difficulty)
                     < std::make_pair(-(double)items[b].rank, -items[b].difficulty); }); break;
    case 4: std::stable_sort(idx.begin(), idx.end(), [&](int a, int b) {
                return std::make_pair((double)items[a].rank, -items[a].difficulty)
                     < std::make_pair((double)items[b].rank, -items[b].difficulty); }); break;
    default: std::stable_sort(idx.begin(), idx.end(), [&](int a, int b) {
                return -face(items[a]) < -face(items[b]); }); break;
    }
    if (attempt >= 6) {
        std::vector<double> key(items.size());
        for (size_t p = 0; p < idx.size(); ++p)
            key[idx[p]] = -(items[idx[p]].difficulty * (0.75 + rng.random() * 0.5));
        std::stable_sort(idx.begin(), idx.end(), [&](int a, int b) { return key[a] < key[b]; });
    }
    return idx;
}

struct Attempt { std::vector<Box> placed; std::vector<int> unplaced; double unplaced_volume, bounding; };

Attempt pack_attempt(const std::vector<Item>& items, const double* cargo, int attempt, Mulberry32& rng,
                     const Opts& o) {
    Attempt A;
    std::vector<Pt> points = {{0.0, 0.0, 0.0}};
    int max_rank = 1;
    bool any = false;
    for (const auto& it : items) { if (!any || it.rank > max_rank) max_rank = it.rank; any = true; }
    if (!any) max_rank = 1;
    double cargo_prod = cargo[0] * cargo[1] * cargo[2];
    std::vector<Pt> cands;
    std::vector<char> placed_flag(items.size(), 0);
    for (int ii : ordered(items, attempt, rng)) {
        const Item& it = items[ii];
        bool have = false; double best_score = 0.0; Box best{};
        for (const auto& rot : it.rot) {
            candidate_positions(points, rot.d, cargo, cands);
            for (const auto& pos : cands) {
                Box c{ii, pos[0], pos[1], pos[2], rot.d[0], rot.d[1], rot.d[2], it.rank, rot.code,
                      it.fragile, it.stackable};
                if (!inside_cargo(c, cargo)) continue;
                bool ov = false;
                for (const auto& b : A.placed) if (boxes_overlap(c, b)) { ov = true; break; }
                if (ov) continue;
                if (o.unload_order && !sequence_compatible(c, A.placed, nullptr)) continue;
                Support s = support_info(c, A.placed, nullptr);
                if (s.ratio + EPS < o.support_ratio) continue;
                bool bad = false;
                if (o.fragility && !c.fragile)
                    for (auto* b : s.boxes) if (b->fragile) { bad = true; break; }
                if (bad) continue;
                for (auto* b : s.boxes) if (!b->stackable) { bad = true; break; }
                if (bad) continue;
                if (o.unload_order)
                    for (auto* b : s.boxes) if (b->rank < c.rank) { bad = true; break; }
                if (bad) continue;
                double target_ratio = (max_rank <= 1) ? 1.0 : (double)(max_rank - c.rank) / (double)(max_rank - 1);
                double target_x = target_ratio * (cargo[0] - c.l);
                double max_x = std::max(c.x + c.l, 0.0), max_y = std::max(c.y + c.w, 0.0), max_z = std::max(c.z + c.h, 0.0);
                for (const auto& b : A.placed) {
                    max_x = std::max(max_x, b.x + b.l); max_y = std::max(max_y, b.y + b.w); max_z = std::max(max_z, b.z + b.h);
                }
                double score = std::fabs(c.x - target_x) / std::max(cargo[0], 1.0) * 700
                    + (c.z + c.h) / std::max(cargo[2], 1.0) * 180
                    + max_x * max_y * max_z / cargo_prod * 80
                    - s.ratio * 60 - contact_score(c, A.placed, cargo) * 4
                    + c.y / std::max(cargo[1], 1.0) * 5;
                if (!have || score < best_score) { have = true; best_score = score; best = c; }
            }
        }
        if (!have) continue;
        A.placed.push_back(best);
        placed_flag[ii] = 1;
        points.push_back({best.x + best.l, best.y, best.z});
        points.push_back({best.x, best.y + best.w, best.z});
        points.push_back({best.x, best.y, best.z + best.h});
        prune_points(points, A.placed, cargo);
    }
    A.unplaced_volume = 0.0;
    for (size_t i = 0; i < items.size(); ++i)
        if (!placed_flag[i]) { A.unplaced.push_back((int)i); A.unplaced_volume += items[i].volume; }
    double mx = 0, my = 0, mz = 0;
    for (const auto& b : A.placed) { mx = std::max(mx, b.x + b.l); my = std::max(my, b.y + b.w); mz = std::max(mz, b.z + b.h); }
    A.bounding = mx * my * mz;
    return A;
}

// Replica _verify (solo lo que puede fallar en un intento completo).
bool verify(const std::vector<Box>& placed, size_t n_items, const double* cargo, const Opts& o) {
    if (placed.size() != n_items) return false;
    for (const auto& b : placed) if (!inside_cargo(b, cargo)) return false;
    for (size_t i = 0; i < placed.size(); ++i)
        for (size_t j = i + 1; j < placed.size(); ++j)
            if (boxes_overlap(placed[i], placed[j])) return false;
    for (const auto& p : placed) {
        Support s = support_info(p, placed, &p);
        if (s.ratio + EPS < o.support_ratio) return false;
        if (o.fragility && !p.fragile) for (auto* b : s.boxes) if (b->fragile) return false;
        for (auto* b : s.boxes) if (!b->stackable) return false;
        if (o.unload_order) {
            for (auto* b : s.boxes) if (b->rank < p.rank) return false;
            if (!sequence_compatible(p, placed, &p)) return false;
        }
    }
    return true;
}

} // namespace

extern "C" {

// Devuelve 0 si ok. Salidas indexadas por item (n): out_placed[i] (0/1),
// out_pos[i*3], out_dims[i*3], out_rot[i]; out_order[k] = item colocado en la
// posicion k (k < *out_n_placed). *out_attempt = intento elegido (1-based),
// *out_verified = 1 si el intento elegido paso la verificacion interna.
int lattimex_pack3d(int n_items,
               const double* dims,        // n*3 originales
               const int32_t* rot_offset, // n+1
               const double* rot_dims,    // R*3
               const int32_t* rot_code,   // R
               const double* volume, const double* weight, const int32_t* rank,
               const uint8_t* fragile, const uint8_t* stackable, const double* difficulty,
               const double* cargo, int max_restarts, uint32_t seed,
               double support_ratio, int enforce_unload_order, int enforce_fragility,
               int32_t* out_order, int32_t* out_n_placed, double* out_pos, double* out_dims,
               int32_t* out_rot, uint8_t* out_placed, int32_t* out_attempt, int32_t* out_verified) {
    if (n_items < 0) return 2;
    std::vector<Item> items((size_t)n_items);
    for (int i = 0; i < n_items; ++i) {
        Item& it = items[i];
        it.index = i;
        for (int k = 0; k < 3; ++k) it.dims[k] = dims[i * 3 + k];
        for (int r = rot_offset[i]; r < rot_offset[i + 1]; ++r)
            it.rot.push_back({{rot_dims[r * 3], rot_dims[r * 3 + 1], rot_dims[r * 3 + 2]}, rot_code[r]});
        it.volume = volume[i]; it.weight = weight[i]; it.difficulty = difficulty[i];
        it.rank = rank[i]; it.fragile = fragile[i] != 0; it.stackable = stackable[i] != 0;
    }
    Opts o{support_ratio, enforce_unload_order != 0, enforce_fragility != 0};
    Mulberry32 rng(seed);
    int attempts = std::max(1, max_restarts);
    bool have = false; Attempt best; std::tuple<size_t, double, double> best_key; int best_attempt = 0;
    int verified = 0;
    for (int a = 0; a < attempts; ++a) {
        Attempt cand = pack_attempt(items, cargo, a, rng, o);
        std::tuple<size_t, double, double> key{cand.unplaced.size(), cand.unplaced_volume, cand.bounding};
        if (!have || key < best_key) { best = cand; best_key = key; best_attempt = a + 1; have = true; }
        if (cand.unplaced.empty() && verify(cand.placed, items.size(), cargo, o)) {
            best = cand; best_key = key; best_attempt = a + 1; verified = 1;
            break;
        }
    }
    std::memset(out_placed, 0, (size_t)n_items);
    for (int i = 0; i < n_items; ++i) { out_order[i] = -1; out_rot[i] = -1; }
    int k = 0;
    for (const auto& b : best.placed) {
        out_order[k++] = b.item;
        out_placed[b.item] = 1;
        out_pos[b.item * 3] = b.x; out_pos[b.item * 3 + 1] = b.y; out_pos[b.item * 3 + 2] = b.z;
        out_dims[b.item * 3] = b.l; out_dims[b.item * 3 + 1] = b.w; out_dims[b.item * 3 + 2] = b.h;
        out_rot[b.item] = b.orient;
    }
    *out_n_placed = k;
    *out_attempt = best_attempt;
    *out_verified = verified;
    return 0;
}

} // extern "C"
