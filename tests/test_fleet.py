import unittest

from src.models.room import Room


class TestFleet(unittest.TestCase):
    def _create_fleet(self):
        from src.engine.fleet import create_room_fleet
        return create_room_fleet()

    def test_fleet_size(self):
        fleet = self._create_fleet()
        self.assertEqual(len(fleet), 200)

    def test_all_building_b01(self):
        fleet = self._create_fleet()
        for room in fleet:
            self.assertEqual(room.building_id, "b01")

    def test_floor_range(self):
        fleet = self._create_fleet()
        floors = {room.floor_id for room in fleet}
        self.assertEqual(floors, set(range(1, 11)))

    def test_rooms_per_floor(self):
        fleet = self._create_fleet()
        for floor in range(1, 11):
            count = sum(1 for r in fleet if r.floor_id == floor)
            self.assertEqual(count, 20)

    def test_protocol_split_100_100(self):
        fleet = self._create_fleet()
        mqtt_count = sum(1 for r in fleet if r.protocol == "mqtt")
        coap_count = sum(1 for r in fleet if r.protocol == "coap")
        self.assertEqual(mqtt_count, 100)
        self.assertEqual(coap_count, 100)

    def test_per_floor_protocol_split(self):
        fleet = self._create_fleet()
        for floor in range(1, 11):
            floor_rooms = [r for r in fleet if r.floor_id == floor]
            mqtt_on_floor = sum(1 for r in floor_rooms if r.protocol == "mqtt")
            coap_on_floor = sum(1 for r in floor_rooms if r.protocol == "coap")
            self.assertEqual(mqtt_on_floor, 10)
            self.assertEqual(coap_on_floor, 10)

    def test_protocol_assignment_by_room_id(self):
        fleet = self._create_fleet()
        for r in fleet:
            if r.room_id <= 10:
                self.assertEqual(r.protocol, "mqtt")
            else:
                self.assertEqual(r.protocol, "coap")


if __name__ == "__main__":
    unittest.main()
