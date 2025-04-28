import prom_spec_pb2,types_pb2
import httpx
import snappy
import time
import json
import asyncio

def main():
    asyncio.run(metrics("testapi","testdevice","testkind",{"test3": 30,"test4": 40}))
    #asyncio.run(query())

async def metrics(project_name: str, device_name: str, kind: str,measurements: dict):
    wr = prom_spec_pb2.WriteRequest()
    metadata = types_pb2.MetricMetadata()
    metadata.type = 1
    metadata.metric_family_name = project_name
    metadata.help = "testmetriken"
    metadata.unit = "bytes"
    wr.metadata.append(metadata)
    for k,v in measurements.items():    
        ts = types_pb2.TimeSeries()
        name_label = types_pb2.Label()
        device_label = types_pb2.Label()
        kind_label = types_pb2.Label()
        sample = types_pb2.Sample()
        name_label.name = "__name__"
        name_label.value = f'{project_name}_{k}'
        device_label.name = "device"
        device_label.value = device_name
        kind_label.name = "kind"
        kind_label.value = kind
        sample.value = v
        sample.timestamp = round(time.time() * 1000)
        ts.labels.append(name_label)
        ts.labels.append(device_label)
        ts.labels.append(kind_label)
        ts.samples.append(sample)
        wr.timeseries.append(ts)




    str_data = snappy.compress(wr.SerializeToString())
    #print(str_data)
    headers = {"Content-Encoding" : "snappy","Content-Type": "application/x-protobuf","User-Agent": "test-agent-1","X-Prometheus-Remote-Write-Version": "0.1.0"}
    async with httpx.AsyncClient() as client:
        r =  await client.post("http://localhost:8081/api/v1/metrics/write",data=str_data,headers=headers)
        print(r.status_code)
        print(r.content)

async def log():
    logstr = {
        "streams": [ {
            "stream": {"test": "test2"},
            "values": [[str(round(time.time() * 1000)),"testmessage"]]
        }]
    }
    logstr = json.dumps(logstr)
    print(logstr)
    async with httpx.AsyncClient() as client:
        headers= {"Content-Type": "application/json"}
        r = await client.post("http://localhost:8082/loki/api/v1/push",data=logstr,headers=headers)
        print(r.status_code)
        print(r.content)

async def query():
    data = {
        "query": "testapi_test",
        "start": "2025-04-16T00:00:00%2B02:00",
        "end": "2025-04-16T13:30:00%2B02:00",
        "step": "15s"
    }
    data = json.dumps(data)
    async with httpx.AsyncClient() as client:
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        r = await client.get("http://localhost:9009/prometheus/api/v1/query_range?query=testapi_test&start=2025-04-16T00:00:00%2B02:00&end=2025-04-16T13:30:00%2B02:00&step=15s",headers=headers)
        
        #r = await client.post("http://localhost:9009/prometheus/api/v1/query_range",data=data,headers=headers)
        print(r.status_code)
        print(r.content)

if __name__ == "__main__":
    main()