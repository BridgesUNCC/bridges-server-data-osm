# osm-bridges-server
Repository for the backend processing and handling of OSM data requests for the BRIDGES project

## Setup
Create a python 3.8 virtual environment. It works also with a 3.6
environment. But likely not a 3.10 environment and further. And reset
the pip packages in the environment from `requirements.txt`.

```bash
$ /opt/python-3.8.10/bin/python3 -m venv myvenv
$ . ./myvenv/bin/activate
$ pip install -r requirements.txt
```

## Launching Flask Server

(Assuming you have activated the environment first. )

Step 1: To launch the flask server first compile the web server
```bash
$ export FLASK_APP=run.py
```

Step 2: Launch the web server 
```bash
$ flask run --host=0.0.0.0 --port=8080
```
--host signifies that the server should use its default IP when listening for requests

--port is the port that it is listening on, the server will be listening on port 8080, unless the server configuration for 8080 redirects to port 80


## Making Queries
To make queries with the server you require two pieces of information, first the bounding box (or city, state) of the area you want returned, and second the filter parameter you want. The both queries can either take in a bounding box of cordinates or a city name and state. 
* Bounding Box
  * minLon
  * minLat
  * maxLon
  * maxLat

* City, State
  * City, State
  
### Map Queries

Map with Bounding Box
```
http://cci-bridges-osm.uncc.edu/coords?minLon=-80.5&minLat=35&maxLon=-80&maxLat=35.5&level=default
```

Map with City Name
```
http://cci-bridges-osm.uncc.edu/loc?location=Chicago, Illinois&level=default
```
To view a list of possible cities visit and the format they should be in visit
[City List](http://cci-bridges-osm.uncc.edu/cities)

* Possible Filtering Values
  * motorway
  * trunk (includes the above too)
  * primary (includes the above too)
  * secondary (includes the above too)
  * tertiary (includes the above too)
  * unclassified (includes the above too)
  * residential (includes the above too)
  * living_street (includes the above too)
  * service (includes the above too)
  * trails
  * walking (includes trails)
  * bicycle (includes tertiary, unclassified, residential and living_street)

If no filter value is given a default value will be used, this default is equivalent to 'unclassified'

### Amenity Queries

Query with Bounding Box
```
http://cci-bridges-osm.uncc.edu/amenity?minLon=-80.5&minLat=35&maxLon=-80&maxLat=35.5&amenity=food
```
Query with City, State
```
http://cci-bridges-osm.uncc.edu/amenity?location=Chicago,%20Illinois&amenity=food
```
*(Note) The '%20' is used to represent a space*

* Possible Filtering Values
  * food
  * school
  * firestation
  * airport
  * heli
  
## Data Format Returned
### OSM
```json
{  
  "nodes": [
    [
      31843386,
      39.1846873,
      -76.8962161
    ],
    [
      31843411,
      39.1844418,
      -76.8964387
    ],
    [
      31843417,
      39.183929,
      -76.8965795
    ]
  ],
  "edges": [
    [
      31843386,
      37190373,
      269.98552269243726
    ],
    [
      31843411,
      37190432,
      210.00120973373004
    ],
    [
      31843417,
      1256047296,
      50.68643531552827
    ]
  ],
  "meta": {
    "lat_min": 39.1210027,
    "lat_max": 39.2079898,
    "lon_min": -77.054985,
    "lon_max": -76.8050138,
    "name": "temp_map"
  }
}
```

### Amenities
node format
```
[
   id
   lat
   lon
   name
   amenity
   FAA (Airport Only)
   IATA (Airport Only)
   ICAO (Airport Only)
]

```
______________________________
```json
{
    "nodes": [
        [
            368381033,
            39.9502553,
            -80.7593715,
            "Glendale Fokker Field",
            "aerodrome",
            null,
            "GWV",
            null
        ],
        [
            368381053,
            39.8811867,
            -80.7356412,
            "Marshall County Airport",
            "aerodrome",
            "MPG",
            null,
            "KMPG"
        ],
        [ ... ]
    ],
    "meta": {
        "count": 127,
        "minlat": 39.0611,
        "minlon": -84.6151,
        "maxlat": 41.8525,
        "maxlon": -80.6106
    }
}
```

## Examples Parameters

### OSM
- "Chicago, Illinois", "default"
- 39.121, -77.055, 39.208, -76.805, "default"
- 40.7866, -73.9225, 40.6809, -74.0625, "default"

### Amenities
- "Chicago, Illinois", "bar,atm,school"
- 35.0809, -80.9700, 35.3457, -80.6693, "food"
- 33.6906, -111.6869, 33.3213, -112.2718, "school"


# How big is the data?

(stats in Dec 2024)

The download of the .pbf file is 16 GB (download is about 30 minutes)

The extracted o5m_main.o5m file is 35GB (and takes not quite an hour on the VM)

The intermediate amenity file filteredTemp.o5m is 268MB (take about 85min)

The intermediate map file mainTemp.o5m is over 4.6GB (and takes over 4 hours; note that generating this file is generated in burst)

the final amenity file is about 130MB

the final map file is about 1.5GB