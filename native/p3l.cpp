// p3l.cpp — P3L, acomodador 3D de una ruta del motor LATTIMEX (desde la versión 1.1.0).
// Copyright (c) 2026 LATTIMEX. Licencia MIT (ver LICENSE).
//
// Problema: colocar las cajas de una ruta en un contenedor L x W x H cumpliendo las restricciones de
// carga de Gendreau et al. (2006), con la misma semántica que el validador público de Krebs:
//   x = largo (puerta en x = L), y = ancho, z = alto; rotación sólo horizontal (l <-> w).
//   soporte: el área de la base apoyada en cajas cuya cara superior está a la altura z es
//            >= alpha * l * w (o la caja está en el piso).
//   fragilidad: una caja no frágil no puede tocar por arriba a una frágil.
//   LIFO (orden de descarga): si e se entrega antes que t, t no puede quedar delante de e (más cerca
//         de la puerta, con proyección y-z común) ni en ningún punto por encima de e (proyección x-y
//         común). El segundo caso, una caja posterior "encima" de una anterior, es el que el empacador
//         de la versión 1.0.0 no impedía.
// Construcción: secuencia de carga + colocación por gravedad en posiciones candidatas (esquinas:
// x de {0, fin de cajas, L-l}, y de {0, fin de cajas, W-w}; z = altura de reposo), regla lexicográfica.
// Búsqueda (flags): bit 1 = esquinas anchas; bit 2 = búsqueda en haz sobre la secuencia; bit 4 = todas
// las posiciones enteras (con soporte) o patrones normales (sin soporte). Mejora: búsqueda local
// iterada sobre la secuencia de carga. Se detiene al colocar todo, o por iteraciones o tiempo.
// Mediciones (rutas óptimas de Tamke et al. 2025 y rutas de producto): paper/guia_senda2.pdf.
//
// Compilar: python -m lattimex build   (o: g++ -O3 -shared -fPIC -o liblattimex_p3l.so p3l.cpp)
#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <numeric>
#include <random>
#include <vector>

namespace {
const double EPS = 1e-6;

struct Item { double l, w, h, vol; int rank; bool fragile, rot; };
struct Box { double x, y, z, l, w, h; int item; };

struct Params {
  double L, W, H, alpha; bool support, fragility, lifo; int rule; bool wide; const std::vector<double>* npx = nullptr; const std::vector<double>* npy = nullptr;
};

inline bool ov(double a0, double a1, double b0, double b1) { return std::min(a1, b1) - std::max(a0, b0) > EPS; }
inline double ovlen(double a0, double a1, double b0, double b1) { return std::max(0.0, std::min(a1, b1) - std::max(a0, b0)); }

struct Packer {
  const std::vector<Item>& it; Params P;
  std::vector<Box> boxes;
  std::vector<double> xs, ys;
  Packer(const std::vector<Item>& items, const Params& p) : it(items), P(p) {}

  // ¿Viola LIFO el par (a, b)? a y b de distinto cliente.
  bool lifo_bad(const Box& a, const Box& b) const {
    int ra = it[a.item].rank, rb = it[b.item].rank;
    if (ra == rb) return false;
    const Box& e = ra < rb ? a : b;   // se entrega antes
    const Box& t = ra < rb ? b : a;   // se entrega después
    // e detrás de t: t entre e y la puerta
    if (e.x + e.l <= t.x + EPS && ov(e.z, e.z + e.h, t.z, t.z + t.h) && ov(e.y, e.y + e.w, t.y, t.y + t.w)) return true;
    // e debajo de t (en cualquier altura)
    if (e.z + e.h <= t.z + EPS && ov(e.x, e.x + e.l, t.x, t.x + t.l) && ov(e.y, e.y + e.w, t.y, t.y + t.w)) return true;
    return false;
  }

  bool feasible(const Box& b) const {
    if (b.x < -EPS || b.y < -EPS || b.z < -EPS || b.x + b.l > P.L + EPS || b.y + b.w > P.W + EPS || b.z + b.h > P.H + EPS) return false;
    double sup = 0.0;
    for (const Box& o : boxes) {
      bool xyov = ov(b.x, b.x + b.l, o.x, o.x + o.l) && ov(b.y, b.y + b.w, o.y, o.y + o.w);
      if (xyov && ov(b.z, b.z + b.h, o.z, o.z + o.h)) return false;
      if (xyov && std::fabs(o.z + o.h - b.z) < EPS) {
        sup += ovlen(b.x, b.x + b.l, o.x, o.x + o.l) * ovlen(b.y, b.y + b.w, o.y, o.y + o.w);
        if (P.fragility && it[o.item].fragile && !it[b.item].fragile) return false;
      }
      if (xyov && std::fabs(b.z + b.h - o.z) < EPS && P.fragility && it[b.item].fragile && !it[o.item].fragile) return false;
      if (P.lifo && lifo_bad(b, o)) return false;
    }
    if (P.support && b.z > EPS && sup + EPS < P.alpha * b.l * b.w) return false;
    return true;
  }

  double rest_z(double x, double y, double l, double w) const {
    double z = 0.0;
    for (const Box& o : boxes)
      if (ov(x, x + l, o.x, o.x + o.l) && ov(y, y + w, o.y, o.y + o.w)) z = std::max(z, o.z + o.h);
    return z;
  }

  // clave lexicográfica (menor es mejor)
  void key(const Box& b, double k[3]) const {
    switch (P.rule) {
      case 0: k[0] = b.x; k[1] = b.z; k[2] = b.y; break;          // fondo primero
      case 1: k[0] = b.z; k[1] = b.x; k[2] = b.y; break;          // capas
      default: k[0] = b.x + b.l; k[1] = b.z; k[2] = b.y; break;   // frente mínimo
    }
  }

  bool place(int i, int rotpref) {
    const Item& I = it[i];
    double best[3] = {1e300, 1e300, 1e300}; Box bb{}; bool found = false;
    for (int r = 0; r < (I.rot ? 2 : 1); ++r) {
      int rr = (r + rotpref) % (I.rot ? 2 : 1);
      double l = rr ? I.w : I.l, w = rr ? I.l : I.w;
      std::vector<double> cx(xs), cy(ys);
      cx.push_back(P.L - l); cy.push_back(P.W - w);
      if (P.npx) { cx = *P.npx; cy = *P.npy; cx.push_back(P.L - l); cy.push_back(P.W - w); }
      else if (P.wide) {   // también pegada antes de cada caja y alineada a su fin
        for (const Box& o : boxes) {
          cx.push_back(o.x - l); cx.push_back(o.x + o.l - l); cx.push_back(o.x);
          cy.push_back(o.y - w); cy.push_back(o.y + o.w - w); cy.push_back(o.y);
        }
        std::sort(cx.begin(), cx.end()); cx.erase(std::unique(cx.begin(), cx.end(), [](double a, double b) { return std::fabs(a - b) < EPS; }), cx.end());
        std::sort(cy.begin(), cy.end()); cy.erase(std::unique(cy.begin(), cy.end(), [](double a, double b) { return std::fabs(a - b) < EPS; }), cy.end());
      }
      for (double x : cx) {
        if (x < -EPS || x + l > P.L + EPS) continue;
        for (double y : cy) {
          if (y < -EPS || y + w > P.W + EPS) continue;
          Box b{x, y, rest_z(x, y, l, w), l, w, I.h, i};
          double k[3]; key(b, k);
          if (!(k[0] < best[0] - EPS || (std::fabs(k[0] - best[0]) <= EPS && (k[1] < best[1] - EPS || (std::fabs(k[1] - best[1]) <= EPS && k[2] < best[2] - EPS)))))
            continue;
          if (!feasible(b)) continue;
          best[0] = k[0]; best[1] = k[1]; best[2] = k[2]; bb = b; found = true;
        }
      }
    }
    if (!found) return false;
    boxes.push_back(bb);
    xs.push_back(bb.x + bb.l); ys.push_back(bb.y + bb.w);
    return true;
  }


  // superficie de contacto con paredes y cajas (mayor es mejor)
  double contact(const Box& b) const {
    double c = 0.0;
    if (b.x < EPS) c += b.w * b.h;
    if (b.y < EPS) c += b.l * b.h;
    if (b.y + b.w > P.W - EPS) c += b.l * b.h;
    if (b.z < EPS) c += b.l * b.w;
    for (const Box& o : boxes) {
      if (std::fabs(o.x + o.l - b.x) < EPS || std::fabs(b.x + b.l - o.x) < EPS) c += ovlen(b.y, b.y + b.w, o.y, o.y + o.w) * ovlen(b.z, b.z + b.h, o.z, o.z + o.h);
      if (std::fabs(o.y + o.w - b.y) < EPS || std::fabs(b.y + b.w - o.y) < EPS) c += ovlen(b.x, b.x + b.l, o.x, o.x + o.l) * ovlen(b.z, b.z + b.h, o.z, o.z + o.h);
      if (std::fabs(o.z + o.h - b.z) < EPS) c += ovlen(b.x, b.x + b.l, o.x, o.x + o.l) * ovlen(b.y, b.y + b.w, o.y, o.y + o.w);
    }
    return c;
  }

  void candidates(int i, std::vector<Box>& out) const {
    const Item& I = it[i];
    for (int r = 0; r < (I.rot ? 2 : 1); ++r) {
      double l = r ? I.w : I.l, w = r ? I.l : I.w;
      if (r && std::fabs(I.l - I.w) < EPS) continue;
      std::vector<double> cx(xs), cy(ys);
      cx.push_back(P.L - l); cy.push_back(P.W - w);
      if (P.npx) { cx = *P.npx; cy = *P.npy; cx.push_back(P.L - l); cy.push_back(P.W - w); }
      else for (const Box& o : boxes) { cx.push_back(o.x - l); cy.push_back(o.y - w); }
      std::sort(cx.begin(), cx.end()); cx.erase(std::unique(cx.begin(), cx.end(), [](double a, double b) { return std::fabs(a - b) < EPS; }), cx.end());
      std::sort(cy.begin(), cy.end()); cy.erase(std::unique(cy.begin(), cy.end(), [](double a, double b) { return std::fabs(a - b) < EPS; }), cy.end());
      for (double x : cx) {
        if (x < -EPS || x + l > P.L + EPS) continue;
        for (double y : cy) {
          if (y < -EPS || y + w > P.W + EPS) continue;
          Box b{x, y, rest_z(x, y, l, w), l, w, I.h, i};
          if (feasible(b)) out.push_back(b);
        }
      }
    }
  }

  // devuelve volumen colocado; deja `boxes`
  double run(const std::vector<int>& seq, const std::vector<int>& rotpref, bool stop_on_fail) {
    boxes.clear(); xs.assign(1, 0.0); ys.assign(1, 0.0);
    double v = 0.0;
    for (size_t k = 0; k < seq.size(); ++k) {
      if (place(seq[k], rotpref[seq[k]])) v += it[seq[k]].vol;
      else if (stop_on_fail) return v;
    }
    return v;
  }
};

// Búsqueda en haz: estado = cajas colocadas. Con LIFO se carga por grupos (último cliente primero);
// dentro del grupo se elige cualquier caja restante. Hijos: para cada caja (tipos distintos) las mejores
// posiciones por regla; puntaje = volumen colocado, luego contacto acumulado, luego frente (x máx) menor.
struct State { std::vector<Box> boxes; std::vector<double> xs, ys; std::vector<uint8_t> used; double vol = 0, cont = 0, front = 0; };

bool beam_search(const std::vector<Item>& items, Params P, int width, int per_item, double deadline_ms,
                 std::chrono::steady_clock::time_point t0, std::vector<Box>& best_out, double& best_vol, long& nodes) {
  int n = (int)items.size();
  auto elapsed = [&] { return std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - t0).count(); };
  std::vector<int> ranks;
  for (auto& I : items) ranks.push_back(I.rank);
  std::sort(ranks.begin(), ranks.end(), std::greater<int>()); ranks.erase(std::unique(ranks.begin(), ranks.end()), ranks.end());
  State s0; s0.used.assign(n, 0); s0.xs = {0.0}; s0.ys = {0.0};
  std::vector<State> beam{s0};
  for (int depth = 0; depth < n; ++depth) {
    std::vector<State> next;
    for (const State& st : beam) {
      // grupo activo: con LIFO el cliente de mayor rango que aún tenga cajas
      int active = -1;
      if (P.lifo) for (int r : ranks) { for (int i = 0; i < n; ++i) if (!st.used[i] && items[i].rank == r) { active = r; break; } if (active >= 0) break; }
      Packer pk(items, P); pk.boxes = st.boxes; pk.xs = st.xs; pk.ys = st.ys;
      std::vector<std::pair<double, Box>> kids;
      std::vector<int> seen_types;
      for (int i = 0; i < n; ++i) {
        if (st.used[i] || (P.lifo && items[i].rank != active)) continue;
        std::vector<Box> c; pk.candidates(i, c);
        // mejores per_item posiciones por (regla lexicográfica) y por contacto
        std::vector<std::pair<double, Box>> sc;
        for (auto& b : c) {
          double k[3]; pk.key(b, k);
          double score = pk.contact(b) / (b.l * b.w + b.l * b.h + b.w * b.h) - 0.02 * (k[0] / P.L) - 0.01 * (k[1] / P.H);
          sc.push_back({score, b});
        }
        std::partial_sort(sc.begin(), sc.begin() + std::min<size_t>(per_item, sc.size()), sc.end(), [](auto& a, auto& b) { return a.first > b.first; });
        for (size_t q = 0; q < sc.size() && (int)q < per_item; ++q) kids.push_back(sc[q]);
      }
      for (auto& kb : kids) {
        State ch = st; ch.boxes.push_back(kb.second); ch.used[kb.second.item] = 1;
        ch.xs.push_back(kb.second.x + kb.second.l); ch.ys.push_back(kb.second.y + kb.second.w);
        ch.vol += items[kb.second.item].vol; ch.cont += kb.first; ch.front = std::max(ch.front, kb.second.x + kb.second.l);
        next.push_back(std::move(ch)); ++nodes;
      }
      if (elapsed() > deadline_ms) break;
    }
    if (next.empty()) break;
    std::sort(next.begin(), next.end(), [](const State& a, const State& b) {
      if (std::fabs(a.vol - b.vol) > EPS) return a.vol > b.vol;
      return a.cont > b.cont; });
    // quitar duplicados (mismo conjunto colocado y mismas posiciones)
    std::vector<State> kept;
    for (auto& c : next) {
      bool dup = false;
      for (auto& k : kept) {
        if (k.used != c.used || std::fabs(k.cont - c.cont) > 1e-9) continue;
        dup = true; break;
      }
      if (!dup) kept.push_back(std::move(c));
      if ((int)kept.size() >= width) break;
    }
    beam.swap(kept);
    if (beam[0].vol > best_vol) { best_vol = beam[0].vol; best_out = beam[0].boxes; }
    if ((int)beam[0].boxes.size() == n) return true;
    if (elapsed() > deadline_ms) break;
  }
  return false;
}
}  // namespace

extern "C" {
// Devuelve 1 si coloca todo. out_pos[3i], out_dims[3i] (l,w,h ya rotados), out_placed[i].
// stats: [0] iteraciones, [1] reinicio exitoso, [2] mejor volumen
int p3l_pack(int n, const double* dims, const int* rank, const uint8_t* fragile,
                                   const uint8_t* rot, double L, double W, double H, int support, double alpha,
                                   int fragility, int lifo, int flags, int max_iters, double time_ms, uint32_t seed,
                                   double* out_pos, double* out_dims, uint8_t* out_placed, double* stats) {
  auto t0 = std::chrono::steady_clock::now();
  auto elapsed = [&] { return std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - t0).count(); };
  std::vector<Item> items(n);
  double total = 0.0;
  for (int i = 0; i < n; ++i) {
    items[i] = {dims[3 * i], dims[3 * i + 1], dims[3 * i + 2], dims[3 * i] * dims[3 * i + 1] * dims[3 * i + 2], rank[i],
                fragile[i] != 0, rot[i] != 0};
    total += items[i].vol;
  }
  std::memset(out_placed, 0, n);
  stats[0] = stats[1] = stats[2] = 0;
  if (n == 0) return 1;
  std::mt19937 rng(seed);
  Params P{L, W, H, alpha, support != 0, fragility != 0, lifo != 0, 0, (flags & 1) != 0};

  // ordenaciones iniciales: LIFO => último cliente primero
  auto base = [&](int kind) {
    std::vector<int> s(n); std::iota(s.begin(), s.end(), 0);
    auto area = [&](int i) { return items[i].l * items[i].w; };
    auto keyf = [&](int i) -> double {
      switch (kind % 4) {
        case 0: return -items[i].vol;
        case 1: return -area(i);
        case 2: return -items[i].h;
        default: return -std::max(items[i].l, items[i].w);
      }
    };
    std::stable_sort(s.begin(), s.end(), [&](int a, int b) {
      if (lifo && items[a].rank != items[b].rank) return items[a].rank > items[b].rank;
      return keyf(a) < keyf(b);
    });
    return s;
  };

  std::vector<double> npx, npy;
  if (flags & 4) {
    auto patterns = [&](double cap) {
      int C = (int)std::floor(cap + EPS);
      std::vector<uint8_t> reach(C + 1, 0); reach[0] = 1;
      for (auto& I : items) {
        std::vector<uint8_t> nr = reach;
        int a = (int)std::llround(I.l), b = (int)std::llround(I.w);
        for (int s = 0; s <= C; ++s) if (reach[s]) {
          if (s + a <= C) nr[s + a] = 1;
          if (I.rot && s + b <= C) nr[s + b] = 1;
        }
        reach.swap(nr);
      }
      std::vector<double> out;
      for (int s = 0; s <= C; ++s) if (reach[s]) out.push_back(s);
      return out;
    };
    npx = patterns(L); npy = patterns(W);
    if (support) {   // con soporte los patrones normales no bastan: todas las posiciones enteras
      npx.clear(); npy.clear();
      for (int v = 0; v <= (int)std::floor(L + EPS); ++v) npx.push_back(v);
      for (int v = 0; v <= (int)std::floor(W + EPS); ++v) npy.push_back(v);
    }
    P.npx = &npx; P.npy = &npy;
  }
  double best_v = -1; std::vector<Box> best_boxes; int it_count = 0;
  bool done = false;
  if (flags & 2) {
    long nodes = 0;
    for (int width : {1, 4, 16, 64, 256}) {
      for (int rule = 0; rule < 2 && !done; ++rule) {
        Params Q = P; Q.rule = rule;
        std::vector<Box> bx; double bv = -1;
        if (beam_search(items, Q, width, 3, time_ms, t0, bx, bv, nodes)) { best_boxes = bx; best_v = total; done = true; stats[1] = width; }
        else if (bv > best_v) { best_v = bv; best_boxes = bx; }
        ++it_count;
        if (elapsed() > time_ms) break;
      }
      if (done || elapsed() > time_ms) break;
    }
  }
  const int RULES = 3, KINDS = 4;
  // fase 1: combinaciones de ordenación x regla
  std::vector<std::pair<std::vector<int>, int>> starts;
  for (int k = 0; k < KINDS; ++k)
    for (int r = 0; r < RULES; ++r) starts.push_back({base(k), r});
  std::vector<int> rotpref(n, 0);
  std::vector<std::pair<double, size_t>> scored;
  for (size_t s = 0; s < starts.size() && !done; ++s) {
    P.rule = starts[s].second;
    Packer pk(items, P);
    double v = pk.run(starts[s].first, rotpref, false);
    ++it_count;
    scored.push_back({v, s});
    if (v > best_v) { best_v = v; best_boxes = pk.boxes; }
    if ((int)pk.boxes.size() == n) { done = true; stats[1] = (double)s; }
  }
  // fase 2: búsqueda local iterada desde los mejores arranques
  std::sort(scored.begin(), scored.end(), [](auto& a, auto& b) { return a.first > b.first; });
  size_t si = 0;
  while (!done && it_count < max_iters && elapsed() < time_ms) {
    size_t s = scored[si % std::min<size_t>(3, scored.size())].second; ++si;
    std::vector<int> cur = starts[s].first; std::vector<int> crot(n, 0);
    P.rule = starts[s].second;
    Packer pk(items, P);
    double cur_v = pk.run(cur, crot, false);
    int stall = 0;
    while (!done && stall < 40 && it_count < max_iters && elapsed() < time_ms) {
      std::vector<int> cand = cur; std::vector<int> crot2 = crot;
      int moves = 1 + (int)(rng() % 2);
      for (int m = 0; m < moves; ++m) {
        int a = (int)(rng() % n);
        if (rng() % 4 == 0) { crot2[cand[a]] ^= 1; continue; }
        int d = 1 + (int)(rng() % 3);
        int b = std::min(n - 1, a + d);
        if (a == b) continue;
        // con LIFO sólo se intercambian cajas del mismo cliente o clientes contiguos
        if (lifo && std::abs(items[cand[a]].rank - items[cand[b]].rank) > 1) continue;
        std::swap(cand[a], cand[b]);
      }
      double v = pk.run(cand, crot2, false);
      ++it_count;
      if (v > best_v) { best_v = v; best_boxes = pk.boxes; }
      if ((int)pk.boxes.size() == n) { done = true; break; }
      if (v >= cur_v - EPS) { if (v > cur_v + EPS) stall = 0; else ++stall; cur = cand; crot = crot2; cur_v = v; }
      else ++stall;
    }
  }
  for (const Box& b : best_boxes) {
    int i = b.item;
    out_pos[3 * i] = b.x; out_pos[3 * i + 1] = b.y; out_pos[3 * i + 2] = b.z;
    out_dims[3 * i] = b.l; out_dims[3 * i + 1] = b.w; out_dims[3 * i + 2] = b.h;
    out_placed[i] = 1;
  }
  stats[0] = it_count; stats[2] = best_v / (total > 0 ? total : 1);
  return (int)best_boxes.size() == n ? 1 : 0;
}
}
