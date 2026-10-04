import unittest
from unittest.mock import patch

import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from test_engine_runtime import er, caja, peticion


class StopAccessTests(unittest.TestCase):
    def test_union_different_blockers_and_four_package_limit(self):
        for count in (2, 4):
            pl = []
            for i in range(count):
                pl += [caja(f'A{i}', 1, 0, i * 60, 0), caja(f'B{i}', 2, 50, i * 60, 0)]
            acc = er._evaluar_acceso([1, 2], pl, ['rear'])
            stop = acc['plan'][0]
            self.assertEqual(set(stop['mover']), {f'B{i}' for i in range(count)})
            self.assertEqual(stop['movimientos'], count)
            self.assertEqual(acc['factible'], count <= 3)
            self.assertEqual(len(stop['entregar']), count)

    def test_shared_blocker_counted_once(self):
        pl = [caja('A1', 1, 0, 0, 0), caja('A2', 1, 0, 50, 0),
              caja('B', 2, 50, 0, 0, w=100)]
        self.assertEqual(er._evaluar_acceso([1, 2], pl)['plan'][0]['mover'], ['B'])

    def test_one_door_for_whole_stop(self):
        # A1 at the left, A2 at the right: independently zero moves; together
        # each side requires removing the middle later-delivery package.
        pl = [caja('A1', 1, 0, 0, 0), caja('B', 2, 0, 50, 0), caja('A2', 1, 0, 100, 0)]
        stop = er._evaluar_acceso([1, 2], pl, ['left', 'right'])['plan'][0]
        self.assertEqual(stop['mover'], ['B'])
        self.assertEqual(stop['movimientos'], 1)
        self.assertEqual([s['guia'] for s in stop['pasos']], ['A1', 'B', 'A2'])

    def test_vertical_dependencies_remove_top_first(self):
        pl = [caja('A', 1, 0, 0, 0), caja('B', 2, 0, 0, 50), caja('C', 3, 0, 0, 100)]
        stop = er._evaluar_acceso([1, 2, 3], pl)['plan'][0]
        self.assertEqual(stop['mover'], ['C', 'B'])
        self.assertEqual(stop['pasos'][-1], {'accion': 'entregar', 'guia': 'A'})

    def test_duplicate_ids_rejected(self):
        with self.assertRaises(ValueError):
            er._evaluar_acceso([1], [caja('A', 1, 0, 0, 0), caja('A', 1, 50, 0, 0)])

    def test_partial_packing_has_no_access_verdict(self):
        req = peticion([(0, 0), (10, 0)], [{'id': 'A', 'node': 1, 'dims_cm': [20]*3}])
        rep = {'status': 'heuristic-unresolved', 'placements': [caja('A', 1, 0, 0, 0)]}
        with patch.object(er, '_pack_route', return_value=rep):
            result = er.solve(req)
        self.assertFalse(result['packing_feasible'])
        self.assertIsNone(result['operational_feasible'])
        self.assertIsNone(result['routes'][0]['acceso'])


if __name__ == '__main__':
    unittest.main()
