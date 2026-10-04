import copy
import unittest
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from test_engine_runtime import er, peticion


def vehicle(length=100, weight=10, doors=None):
    return {'cargo_cm': [length, 100, 100], 'max_weight_kg': weight, 'doors': doors or ['rear']}


def request(fleet, packages):
    nodes = max(p['node'] for p in packages)
    req = peticion([(i*10, 0) for i in range(nodes+1)], packages, budget=.2)
    req.pop('vehicle'); req['fleet'] = fleet; req['fleet_count'] = len(fleet)
    return req


class FleetTests(unittest.TestCase):
    def assert_physical(self, result, req):
        self.assertTrue(result['feasible'])
        self.assertEqual(len(result['routes']), len(req['fleet']))
        self.assertEqual(sorted(r['vehicle_index'] for r in result['routes']), list(range(len(req['fleet']))))
        seen = []
        packages = {p['id']: p for p in req['packages']}
        for route in result['routes']:
            seen += route['packages']
            v = req['fleet'][route['vehicle_index']]
            self.assertLessEqual(sum(packages[p].get('weight_kg', 0) for p in route['packages']), v['max_weight_kg'])
            self.assertEqual(route['acceso']['puertas_disponibles'], v['doors'])
            for placement in route['placements']:
                for x, size, limit in zip(('x','y','z'), ('lengthCm','widthCm','heightCm'), v['cargo_cm']):
                    self.assertGreaterEqual(placement[x], 0)
                    self.assertLessEqual(placement[x]+placement[size], limit+1e-6)
        self.assertEqual(sorted(seen), sorted(packages))

    def test_long_package_uses_actual_large_vehicle(self):
        req = request([vehicle(), vehicle(200)], [
            {'id':'A','node':1,'dims_cm':[180,20,20],'keep_upright':True},
            {'id':'B','node':2,'dims_cm':[20,20,20]}])
        original = copy.deepcopy(req)
        result = er.solve(req); self.assert_physical(result, req)
        self.assertIn('A', result['routes'][1]['packages'])
        self.assertEqual(req, original)

    def test_weight_and_individual_doors(self):
        req = request([vehicle(weight=1), vehicle(weight=10, doors=['rear','right'])], [
            {'id':'A','node':1,'dims_cm':[20]*3,'weight_kg':5},
            {'id':'B','node':2,'dims_cm':[20]*3,'weight_kg':1}])
        result = er.solve(req); self.assert_physical(result, req)
        self.assertEqual(result['routes'][1]['packages'], ['A'])

    def test_declared_volume_limits_assignment(self):
        small = dict(vehicle(), max_volume_cm3=9000)
        req = request([small, vehicle(200)], [
            {'id':'A','node':1,'dims_cm':[30]*3}, {'id':'B','node':2,'dims_cm':[20]*3}])
        result = er.solve(req); self.assert_physical(result, req)
        self.assertEqual(result['routes'][0]['packages'], ['B'])

    def test_multiple_packages_stay_at_one_customer(self):
        req = request([vehicle(), vehicle(200)], [
            {'id':'A1','node':1,'dims_cm':[180,20,20]},
            {'id':'A2','node':1,'dims_cm':[30]*3}, {'id':'B','node':2,'dims_cm':[20]*3}])
        result = er.solve(req); self.assert_physical(result, req)
        self.assertEqual(set(result['routes'][1]['packages']), {'A1','A2'})
        self.assertEqual(result['routes'][1]['acceso']['entregas'], 1)

    def test_incompatible_upright_is_unresolved_not_certified(self):
        req = request([vehicle(), vehicle(200)], [
            {'id':'A','node':1,'dims_cm':[20,20,150],'keep_upright':True},
            {'id':'B','node':2,'dims_cm':[20]*3}])
        result = er.solve(req)
        self.assertFalse(result['feasible'])
        self.assertEqual(result['solution_status'], 'heuristic-unresolved')
        self.assertIsNone(result['operational_feasible'])

    def test_homogeneous_and_legacy_keep_exact_fleet(self):
        req = request([vehicle(), vehicle()], [
            {'id':'A','node':1,'dims_cm':[20]*3}, {'id':'B','node':2,'dims_cm':[20]*3}])
        self.assert_physical(er.solve(req), req)
        legacy = dict(req, vehicle=req['fleet'][0]); legacy.pop('fleet')
        self.assertEqual([r['vehicle_index'] for r in er.solve(legacy)['routes']], [0,1])

    def test_sequence_optimization_retains_all_packages_and_assignments(self):
        req = request([vehicle(), vehicle(200)], [
            {'id':f'P{i}','node':i,'dims_cm':[20]*3,'weight_kg':.2} for i in range(1,13)])
        self.assert_physical(er.solve(req), req)

    def test_fleet_count_mismatch_rejected(self):
        req = request([vehicle(), vehicle(200)], [
            {'id':'A','node':1,'dims_cm':[20]*3}, {'id':'B','node':2,'dims_cm':[20]*3}])
        req['fleet_count'] = 1
        with self.assertRaises(ValueError):
            er.solve(req)

    def test_cache_does_not_reuse_large_vehicle_packing_for_small(self):
        req = request([vehicle(), vehicle(200)], [
            {'id':'A','node':1,'dims_cm':[180,20,20]}, {'id':'B','node':2,'dims_cm':[20]*3}])
        small = er._normalized_source(dict(req, vehicle=req['fleet'][0]), 1)
        large = er._normalized_source(dict(req, vehicle=req['fleet'][1]), 1)
        items = er._items_by_customer(large); cache = {}
        self.assertEqual(er._pack_route(large, [1], 0, items, 'loading-only', cache, restarts=(1,))['status'], 'heuristic-feasible')
        self.assertNotEqual(er._pack_route(small, [1], 0, items, 'loading-only', cache, restarts=(1,))['status'], 'heuristic-feasible')


if __name__ == '__main__':
    unittest.main()
