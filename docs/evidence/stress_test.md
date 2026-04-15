# HiveMQ Stress Test Evidence

Captured: 2026-04-15 13:11:13 UTC

## Live traffic sampling

```
$ timeout 10 mosquitto_sub -h localhost -p 1883 -t 'campus/#' -v
...
  total messages: 918
  throughput: ~91 msg/s

  distinct sensor_ids: 200 / 200
  distinct topics: 388

  leaf topic breakdown:
        559 heartbeat
        359 telemetry
```

## First 10 messages (format sample)

```
campus/b01/f09/r916/heartbeat {"sensor_id": "b01-f09-r916", "timestamp": 1776258650, "status": "online"}
campus/b01/f02/r208/heartbeat {"sensor_id": "b01-f02-r208", "timestamp": 1776258647, "status": "online"}
campus/b01/f06/r602/heartbeat {"sensor_id": "b01-f06-r602", "timestamp": 1776258651, "status": "online"}
campus/b01/f07/r704/heartbeat {"sensor_id": "b01-f07-r704", "timestamp": 1776258647, "status": "online"}
campus/b01/f08/r814/heartbeat {"sensor_id": "b01-f08-r814", "timestamp": 1776258650, "status": "online"}
campus/b01/f07/r712/heartbeat {"sensor_id": "b01-f07-r712", "timestamp": 1776258649, "status": "online"}
campus/b01/f01/r106/heartbeat {"sensor_id": "b01-f01-r106", "timestamp": 1776258641, "status": "online"}
campus/b01/f10/r1001/heartbeat {"sensor_id": "b01-f10-r1001", "timestamp": 1776258650, "status": "online"}
campus/b01/f09/r908/heartbeat {"sensor_id": "b01-f09-r908", "timestamp": 1776258651, "status": "online"}
campus/b01/f06/r610/heartbeat {"sensor_id": "b01-f06-r610", "timestamp": 1776258647, "status": "online"}
```

## Docker container state

```
NAME                                                                STATUS
campus-engine                                                       Up 15 minutes
campus-hivemq                                                       Up 12 hours
campus-tb-postgres                                                  Up 12 hours
campus-thingsboard                                                  Up 12 hours
distributed-intelligent-campus-iot-environment-gateway-floor-01-1   Up 11 hours (healthy)
distributed-intelligent-campus-iot-environment-gateway-floor-02-1   Up 11 hours (healthy)
distributed-intelligent-campus-iot-environment-gateway-floor-03-1   Up 12 hours (healthy)
distributed-intelligent-campus-iot-environment-gateway-floor-04-1   Up 12 hours (healthy)
distributed-intelligent-campus-iot-environment-gateway-floor-05-1   Up 12 hours (healthy)
distributed-intelligent-campus-iot-environment-gateway-floor-06-1   Up 12 hours (healthy)
distributed-intelligent-campus-iot-environment-gateway-floor-07-1   Up 12 hours (healthy)
distributed-intelligent-campus-iot-environment-gateway-floor-08-1   Up 12 hours (healthy)
distributed-intelligent-campus-iot-environment-gateway-floor-09-1   Up 12 hours (healthy)
distributed-intelligent-campus-iot-environment-gateway-floor-10-1   Up 12 hours (healthy)
```
