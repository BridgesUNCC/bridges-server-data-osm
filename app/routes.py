from app import app
from flask import request
import subprocess
import json
import app.osm_to_adj as osm_to_adj
import app.map_update as map_update
import os
import shutil
import sys
import resource
import logging
from logging.handlers import RotatingFileHandler, StreamHandler
import time
import hashlib
import pickle
import io
from apscheduler.schedulers.background import BackgroundScheduler
import xml.etree.ElementTree as ET

memPercent = None # % of RAM allowed for osm_to_adj.py to use
degreeRound = 4 #number of decimal places to round bounding box coords too
maxMapFolderSize = None  #change first value to set number of gigabits the map folder should be
LRU = []

default = '--keep=\"highway=motorway =trunk =primary =secondary =tertiary =unclassified =primary_link =secondary_link =tertiary_link =trunk_link =motorway_link\" --drop-version'
motorway = '=motorway =motorway_link'
trunk = ' =trunk =trunk_link'
primary = ' =primary =primary_link'
secondary = ' =secondary =secondary_link'
tertiary = ' =tertiary =tertiary_link'
unclassified = ' =unclassified'
residential = ' =residential'
living_street = ' =living_street'
service = ' =service'
trails = ' =path =footway'
bicycle = ' =cycleway'
walking = ' =pedestrian'


divider = "-----------------------------------------------------------------"


# This takes the output of the server and adds the appropriate headers to make the security team happy
def harden_response(message_str):
    response = app.make_response(message_str)
    response.headers['Content-Security-Policy'] = "default-src 'self'"
    response.headers['X-Frame-Options'] = 'SAMEORIGIN'
    return response

def sanitize_location_name(name: str):
    new_name = str(name)
    new_name = new_name.lower().replace(",", "").replace(" ", "").replace(".","").replace("-","").replace("(","").replace(")","").replace("'","")
    return new_name

@app.route('/amenity')
def amenity():
    '''
    Query Parameter:
    where:
    -minLat: a float
    -minLon: a float
    -maxLat: a float
    -maxLon: a float
    -location: a string that contains a city name as returned as part of /cities

    what:
    -amenity: a type of amenity
    '''
    try:
        try:
            if((request.args['minLat'] is not None) and (request.args['minLon'] is not None) and (request.args['maxLat'] is not None) and (request.args['maxLon'] is not None) and (request.args['amenity'] is not None)):    
                input_Value = [round(float(request.args['minLat']), degreeRound), round(float(request.args['minLon']), degreeRound), round(float(request.args['maxLat']), degreeRound), round(float(request.args['maxLon']), degreeRound)]
                amenity_type = request.args['amenity']
                app_log.info(divider)
                app_log.info(f"Requester: {request.remote_addr}")
                app_log.info(f"Script started with Box: {request.args['minLat']}, {request.args['minLon']}, {request.args['maxLat']}, {request.args['maxLon']} bounds and the amenity: {request.args['amenity']}")
        except:
            pass
        
        try:
            if((request.args['location'] is not None) and (request.args['amenity'] is not None)):
                input_Value = city_coords(sanitize_location_name(request.args['location']))
                amenity_type = request.args['amenity']
                app_log.info(divider)
                app_log.info(f"Requester: {request.remote_addr}")
                app_log.info(f"Script started with City: {request.args['location']} Box: {request.args['minLat']}, {request.args['minLon']}, {request.args['maxLat']}, {request.args['maxLon']} bounds and the amenity: {request.args['amenity']}")
        except:
            pass

        if(amenity_type is None):
            raise

    except:
            print("System arguments are invalid")
            app_log.exception(f"System arguments invalid {request.args}")
            return harden_response("Invalid arguments")
    

    
    #Check to see if amenity data has already been computed
    dir = f"app/reduced_maps/coords/{input_Value[0]}/{input_Value[1]}/{input_Value[2]}/{input_Value[3]}/{amenity_type}"
    if (os.path.isfile(f"{dir}/amenity_data.json")):
        app_log.info(f"Amenity data set already generated")
        f = open(f"{dir}/amenity_data.json")
        data = json.load(f)
        f.close()
        return  json.dumps(data, sort_keys = False, indent = 2)



    o5m = call_convert1(map_update.amenityfile(), input_Value)
    filename = callAmenityFilter(o5m, amenity_type)


    tree = ET.parse(filename)
    root = tree.getroot()

    out_nodes = []
    num_val = 0
    for child in root:
        if(child.get('id') == None or child.get('lat') == None or child.get('lon') == None):
            continue
        amenity = None
        aero = None
        name = None
        faa = None
        iata = None
        icao = None
        id_val = int(child.get('id'))
        lat = float(child.get('lat'))
        lon = float(child.get('lon'))
        if (amenity_type != "airport" and amenity_type != "heli"): #searches for amenities
            for x in child:
                if (x.attrib.get('k') == 'name'):
                    name = x.attrib.get('v') 
                if (x.attrib.get('k') == 'amenity'):  
                    amenity = x.attrib.get('v')

            if (name == None or amenity == None):
                continue

            num_val += 1
            out_nodes.append([id_val, lat, lon, name, amenity])

        else: # Searches for aeroway values
            for x in child:
                if (x.attrib.get('k') == 'name'):
                    name = x.attrib.get('v') 
                if (x.attrib.get('k') == 'aeroway'):  
                    aero = x.attrib.get('v')
                if (x.attrib.get('k') == 'faa'):  
                    faa = x.attrib.get('v')
                if (x.attrib.get('k') == 'iata'):  
                    iata = x.attrib.get('v')
                if (x.attrib.get('k') == 'icao'):  
                    icao = x.attrib.get('v')

            if (name == None or aero == None):
                continue

            num_val += 1
            out_nodes.append([id_val, lat, lon, name, aero, faa, iata, icao])

        
    # http://127.0.0.1:5000/amenity?minLon=-80.97006&minLat=35.08092&maxLon=-80.6693&maxLat=35.3457

    app_log.info(f"Number of Nodes found: {num_val}")
    meta_data = {}
    meta_data['count'] = num_val
    if (len(input_Value) == 4):
        meta_data['minlat'] = input_Value[0]
        meta_data['minlon'] = input_Value[1]
        meta_data['maxlat'] = input_Value[2]
        meta_data['maxlon'] = input_Value[3]

    node = {}
    node['nodes'] = out_nodes
    node['meta'] = meta_data 
    
    try:
        os.remove(o5m)
        os.remove(filename)
    except:
        pass

    #Save map data to server storage
    dir = f"app/reduced_maps/coords/{input_Value[0]}/{input_Value[1]}/{input_Value[2]}/{input_Value[3]}/{amenity_type}"
    
    try:
        os.makedirs(dir)
    except:
        pass

    with open(f"{dir}/amenity_data.json", 'w') as x:
        json.dump(node, x, indent=4)



    try:
        md5_hash = hashlib.md5()
        with open(f"{dir}/amenity_data.json","rb") as f:
            # Read and update hash string value in blocks of 4K
            for byte_block in iter(lambda: f.read(4096),b""):
                md5_hash.update(byte_block)
            app_log.info("Hash: " + md5_hash.hexdigest())
        with open(f"{dir}/hash.txt", "w") as h:
            h.write(md5_hash.hexdigest())
    except:
        app_log.exception("Hashing error occured")



    return json.dumps(node)

@app.route('/loc')
def namedInput():
    '''
    Query Param:
    Where:
    -minLon: a float
    -maxLon: a float
    -minLat: a float
    -maxLat: a float
    -location: A string mapping to a city as returned by /cities
    What:
    -level:
    '''
    try:
        input_Value = sanitize_location_name(request.args['location'])
        app_log.info(divider)
        app_log.info(f"Requester: {request.remote_addr}")
        app_log.info(f"Script started with {request.args['location']} parameters")
        if not all(x.isalpha() or x == "'" for x in input_Value):
            raise ValueError()
    except:
        print("System arguments are invalid")
        app_log.exception(f"System arguments invalid {request.args['location']}")
        return harden_response("Invalid arguments")

    try:
        if (request.args['level'].lower() == 'motorway' or request.args['level'].lower() == 'trunk' or request.args['level'].lower() == 'primary' or request.args['level'].lower() == 'secondary' or request.args['level'].lower() == 'tertiary' or request.args['level'].lower() == 'unclassified'):
            level = str(request.args['level'])
            app_log.info(f"Script using street detail level of: {request.args['level']}")
        else:
            level = "default"
            app_log.info(f"Script using street detail level of default (full detail)")
    except:
        level = "default"
        app_log.info(f"Script using street detail level of default (full detail)")



    try:
        coords = city_coords(input_Value)
        if (coords != 404):
            return harden_response(pipeline(coords, level, input_Value))
        else:
            return harden_response(page_not_found())
    except:
        app_log.info(f"Error occured while processing city: {input_Value}")
        return harden_response(server_error())

@app.route('/coords')
def coordsInput():

    try:
        #rounds and converts the args to floats and rounds to a certain decimal
        input_Value = [round(float(request.args['minLat']), degreeRound), round(float(request.args['minLon']), degreeRound), round(float(request.args['maxLat']), degreeRound), round(float(request.args['maxLon']), degreeRound)]
        app_log.info(divider)
        app_log.info(f"Requester: {request.remote_addr}")
        app_log.info(f"Script started with Box: {request.args['minLat']}, {request.args['minLon']}, {request.args['maxLat']}, {request.args['maxLon']} bounds")
    except:
        print("System arguments are invalid")
        app_log.exception(f"System arguments invalid {request.args}")
        return harden_response("Invalid arguments")

    try:
        if (request.args['level'] is not None): #request.args['level'].lower() == 'motorway' or request.args['level'].lower() == 'trunk' or request.args['level'].lower() == 'primary' or request.args['level'].lower() == 'secondary' or request.args['level'].lower() == 'tertiary' or request.args['level'].lower() == 'unclassified'):
            level = str(request.args['level'])
            app_log.info(f"Script attempting to use street detail level of: {request.args['level']}")
        else:
            level = "default"
            app_log.info(f"Script using street detail level of default (full detail)")
    except:
        level = "default"
        app_log.info(f"Script using street detail level of default (full detail)")

    return harden_response(pipeline(input_Value, level))


#Updated route to handle both bbox and city
@app.route('/map')
def map_request():
    minLat = request.args.get("minLat")
    minLon = request.args.get("minLon")
    maxLat = request.args.get("maxLat")
    maxLon = request.args.get("maxLon")
    city = request.args.get("city")
    level = request.args.get("level")

    if ((minLat != None) and (minLon != None) and (maxLat != None) and (maxLon != None)):
        bbox = [round(float(minLat), degreeRound), round(float(minLon), degreeRound), round(float(maxLat), degreeRound), round(float(maxLon), degreeRound)]
    elif (city != None):
        city = sanitize_location_name(city)
        bbox = city_coords(city)
    else:
         return harden_response("Invalid arguments")

    if level is None:
        level = "default"


    return harden_response(updated_pipeline(bbox, level))



@app.route('/hash')
def hashreturn():
    type = None
    loc = None

    amenity = request.args.get('amenity')
    level = request.args.get('level')
    if (level != None):
        try:
            loc = sanitize_location_name(request.args['location'])
            input_Value = city_coords(loc)
            type = "loc"
            app_log.info(divider)
            app_log.info(f"Requester: {request.remote_addr}")
            app_log.info(f"Hash checking for map with bounds: {input_Value[0]}, {input_Value[1]}, {input_Value[2]}, {input_Value[3]}")
        except:
            try:
                #rounds and converts the args to floats and rounds to a certain decimal
                input_Value = [round(float(request.args['minLat']), degreeRound), round(float(request.args['minLon']), degreeRound), round(float(request.args['maxLat']), degreeRound), round(float(request.args['maxLon']), degreeRound)]
                type = "coord"
                app_log.info(divider)
                app_log.info(f"Requester: {request.remote_addr}")
                app_log.info(f"Hash checking for map with bounds: {input_Value[0]}, {input_Value[1]}, {input_Value[2]}, {input_Value[3]}")
            except:
                print("System arguments for hash check are invalid")
                app_log.exception(f"System arguments for hash check invalid {request.args['minLat']}, {request.args['minLon']}, {request.args['maxLat']}, {request.args['maxLon']}")
                return harden_response("Invalid arguments")

        if (type == "loc"):
            dir = f"app/reduced_maps/cities/{loc}/{level}"
        elif (type == "coord"):
            dir = f"app/reduced_maps/coords/{input_Value[0]}/{input_Value[1]}/{input_Value[2]}/{input_Value[3]}/{level}"
        else:
            return harden_response(page_not_found())


    elif (amenity != None):
        
        try:
            city = request.args.get('location')
            if (city == None):
                input_Value = [round(float(request.args['minLat']), degreeRound), round(float(request.args['minLon']), degreeRound), round(float(request.args['maxLat']), degreeRound), round(float(request.args['maxLon']), degreeRound)]
            else:
                input_Value = city_coords(sanitize_location_name(request.args['location']))
            dir = f"app/reduced_maps/coords/{input_Value[0]}/{input_Value[1]}/{input_Value[2]}/{input_Value[3]}/{amenity}"
        except:
            return harden_response(page_not_found)

    try:
        with open(f"{dir}/hash.txt", 'r') as f:
            re = f.readlines()
            app_log.info(f"Hash value found: {re[0]}")
            return harden_response(re[0])
    except:
        print("No map hash found")
        return harden_response("false")

@app.route('/cities')
def cityNameReturns():
    outStr = ""
    with open('app/cities.json', 'r') as x:
        city_json = json.load(x)
        return harden_response(json.dumps(city_json))

@app.route('/favicon.ico')
def icon():
    return ''

@app.route('/')
def noinput():
    return harden_response(page_not_found())

@app.errorhandler(404)
def page_not_found(e=''):
    return harden_response("Not a valid URL")

@app.errorhandler(500)
def server_error(e=''):
    return harden_response("Server Error occured while attempting to process your request. Please try again...")

def call_convert1(filename, box=[]):
    """Creates a process of the osmconvert, to shrink the map file down to a bounding box as well as change the file type to .o5m

    Parameters:
    filename(str): String of the file path to the map
    box(list): list of longitude and latitude coordinates

    Returns:
    string: String of the directory that the o5m file was generated in

    """

    try:
        bbox = f" -b=\"{box[1]},{box[0]},{box[3]},{box[2]}\""
        command  = (f"app/osm_converts/osmconvert64 " + filename + bbox + f" --all-to-nodes -o=app/o5m_Temp.o5m")
        app_log.info(f"Converting {box[0]}, {box[1]}, {box[2]}, {box[3]} map to .o5m with only nodes using : "+command)
    except:
        command  = (f"app/osm_converts/osmconvert64 " + filename + f" -o=app/o5m_Temp.o5m")
        app_log.info(f"Converting {box[0]}, {box[1]}, {box[2]}, {box[3]} map to .o5m using : "+command)

    try:
        start_time = time.time()
        subprocess.run([command], shell=True)
        app_log.info("Map Successfully Converted to .o5m in: %s" % (time.time() - start_time))
    except:
        print("Error converting file to .o5m")
        app_log.exception(f"Exception occurred while converting bounds: {box[0]}, {box[1]}, {box[2]}, {box[3]}")

    return f"app/o5m_Temp.o5m"

def call_convert2(filename, box=[]):
    """Creates a process of the osmconvert, to shrink the map file down to a bounding box as well as change the file type to .o5m

    Parameters:
    filename(str): String of the file path to the map
    box(list): list of longitude and latitude coordinates

    Returns:
    string: String of the directory that the o5m file was generated in

    """

    try:
        bbox = f" -b=\"{box[1]},{box[0]},{box[3]},{box[2]}\""
        command  = (f"app/osm_converts/osmconvert64 " + filename + bbox + f" -o=app/o5m_Temp.o5m")
        app_log.info(f"Converting {box[0]}, {box[1]}, {box[2]}, {box[3]} map to .o5m with only nodes using : "+command)
    except:
        command  = (f"app/osm_converts/osmconvert64 " + filename + f" -o=app/o5m_Temp.o5m")
        app_log.info(f"Converting {box[0]}, {box[1]}, {box[2]}, {box[3]} map to .o5m using : "+command)

    try:
        start_time = time.time()
        subprocess.run([command], shell=True)
        app_log.info("Map Successfully Converted to .o5m in: %s" % (time.time() - start_time))
    except:
        print("Error converting file to .o5m")
        app_log.exception(f"Exception occurred while converting bounds: {box[0]}, {box[1]}, {box[2]}, {box[3]}")

    return f"app/o5m_Temp.o5m"


def call_filter(o5m_filename, level):
    """Creates a process of the osmfilter to remove any info that we dont need

    Parameters:
    o5m_filename(str): Name of the file that the the filter will look for

    Returns:
    string: String of the directory that the xml file was generated in
    """

    area = "xml_Temp"

    para = "--keep=\"highway"

    if (level == "motorway"):
        para = para + motorway
    elif (level == "trunk"):
        para = para + motorway + trunk
    elif (level == "primary"):
        para = para + motorway + trunk + primary
    elif (level == "secondary"):
        para = para + motorway + trunk + primary + secondary
    elif (level == "tertiary"):
        para = para + motorway + trunk + primary + secondary + tertiary
    elif (level == "unclassified"):
        para = para + motorway + trunk + primary + secondary + tertiary + unclassified
    elif (level == "residential"):
        para = para + motorway + trunk + primary + secondary + tertiary + unclassified + residential
    elif (level == "living_street"):
        para = para + motorway + trunk + primary + secondary + tertiary + unclassified + residential + living_street
    elif (level == "service"):
        para = para + motorway + trunk + primary + secondary + tertiary + unclassified + residential + living_street + service
    elif (level == "trails"):
        para = para + trails
    elif (level == "walking"):
        para = para + trails + walking
    elif  (level == "bicycle"):
        para = para + bicycle + tertiary + unclassified + residential + living_street
    else:
        para = default

    para = para + "\" --drop-version"

    if (level == "default"):
        para = default

    command = f"app/osm_converts/osmfilter {o5m_filename} " + para + f" -o=app/{area}.xml"
    try:
        start_time = time.time()
        app_log.info(f"Starting osmfilter on {o5m_filename} with filter command level {level} using "+command)
        subprocess.run([command], shell=True)
        app_log.info("Filtering Complete in: %s" % (time.time() - start_time))
    except:
        print("Error while filtering data")
        app_log.exception(f"Exception while filtering data on map: {o5m_filename}")

    return f"app/{area}.xml"

def callAmenityFilter(o5m_filename, filter):

    para = '--keep=\"'

    if (filter == "food"):
        para= para + "amenity=fast_food =restaurant =cafe =ice_cream =bar "
    elif(filter == "school"):   
        para = para + "amenity=college =kindergarten =school =university "
    elif (filter == "firestation"):
        para = para + "amenity=fire_station "
    elif (filter == "airport"):    
        para = para + "aeroway=aerodrome "
    elif (filter == "heli"):
        para = para + "aeroway=helipad "
    else:
        #TODO: Parse custom filter
        filters = filter.replace(" ", "").split(',')
        para = para + "amenity"
        for f in filters:
            para = para + f"={f} "
        pass

    para = para + "\"--drop-version --ignore-dependencies"

    command = f"app/osm_converts/osmfilter {o5m_filename} " + para + " -o=app/temp2.xml"

    try:
        start_time = time.time()
        app_log.info(f"Starting amenity filter on {o5m_filename} with filter {filter} using command: {command}")
        
        subprocess.run([command], shell=True)
        app_log.info("Filtering Complete in: %s" % (time.time() - start_time))
    except:
        print("Error with filtering parameters")
        app_log.exception(f"Exception while filtering data on map: {o5m_filename}")

    return f"app/temp2.xml"


def get_memory():
    '''Retreives current amount of free memory

    Returns:
    int: int of KB of memory free

    '''
    with open('/proc/meminfo', 'r') as mem:
        free_memory = 0
        for i in mem:
            sline = i.split()
            if str(sline[0]) in ('MemFree:', 'Buffers:', 'Cached:'):
                free_memory += int(sline[1])
    return free_memory




def city_coords(location):
    ''' Calculates the bounding box for a given city

        Parameters:
            location(str): Name of the city the user requested

        Returns:
            list[floats]: bounding box for a given city name
    '''
    coord = None
    try:
        with open('app/cities.json', 'r') as x:
            loaded = json.load(x)
            for city in loaded:
                cityState = sanitize_location_name(city['city'] + city['state'])
                if (cityState.lower() == location):
                        minLat = round(float(city['latitude']) - .1, degreeRound)
                        minLon = round(float(city['longitude']) - .1, degreeRound)
                        maxLat = round(float(city['latitude']) + .1, degreeRound)
                        maxLon = round(float(city['longitude']) + .1, degreeRound)
                        coord = [minLat, minLon, maxLat, maxLon]
                        return coord
        if (coord == None):
            print ("Please put a location that is supported")
            return page_not_found()
    except Exception as e:
        app_log.info(e)

def map_size(coords, level):
    ''' Calculates whether a bounding box is within the size limits of a certain detail level

        Parameters:
            coords(list): Bounding box of map requested
            level(str): detail level the user requested

        Returns:
            boolean: returns true if bounding box given is within size limit of detail level
    '''
    if (level == "motorway"):
        limit = 20
    elif (level == "trunk"):
        limit = 10
    elif (level == "primary"):
        limit = 5
    elif (level == "secondary"):
        limit = 2
    elif (level == "tertiary"):
        limit = 1.5
    elif (level == "unclassified"):
        limit = 1
    elif (level == "living_street" or level == "residential" or level == "service"):
        limit = .5
    elif (level == "bicycle" or level == "trails"):
        limit = 2
    else:
        limit = 1


    if (abs(abs(coords[2]) - abs(coords[0])) > limit or abs(abs(coords[3]) - abs(coords[1])) > limit):
        return True
    return False

def getFolderSize():
    ''' Calculates the size of the maps folder

        Returns:
            int: size of app/reduced_maps folder in bytes
    '''
    try:
        size = 0
        start_path = 'app/reduced_maps'  # To get size of directory
        for path, dirs, files in os.walk(start_path):
            for f in files:
                fp = os.path.join(str(path), str(f))
                size = size + os.path.getsize(fp)
        return size
    except Exception as e:
        return (e)

def lruUpdate(location, level, name=None):
    ''' Updates the LRU list and storage file

        Parameters:
            location(list[float]): a maps bounding box
            level(string): the level of detail a map hash
            name(string): the name of the city that the map represents

        Return:
            None
    '''
    if (name == None):
        try: # Removes the location requested by the API from the LRU list
            LRU.remove([location[0], location[1], location[2], location[3], level])
        except:
            pass
        #Adds in the requested location into the front of the list
        LRU.insert(0, [location[0], location[1], location[2], location[3], level])
        #Removes old maps from server while the map folder is larger than set limit
        while (getFolderSize() > maxMapFolderSize):
            #Removes map from server
            try:
                re = LRU[len(LRU)-1]
                if (os.path.isdir(f"app/reduced_maps/coords/{re[0]}/{re[1]}/{re[2]}/{re[3]}/{re[4]}")):
                    shutil.rmtree(f"app/reduced_maps/coords/{re[0]}/{re[1]}/{re[2]}/{re[3]}/{re[4]}")
                    del LRU[len(LRU)-1]
                elif(os.path.isdir(f"app/reduced_maps/cities/{re[0]}/{re[1]}")):
                    shutil.rmtree(f"app/reduced_maps/cities/{re[0]}/{re[1]}")
                    del LRU[len(LRU)-1]
            except:
                print("ERROR Deleteing map File")
        #updates the LRU file incase the server goes offline or restarts
        with open("lru.txt", "wb") as fp:   #Pickling
            pickle.dump(LRU, fp)
    elif(name != None):
        try:
            LRU.remove([name, level])
        except:
            pass
        LRU.insert(0, [name, level])
        while (getFolderSize() > maxMapFolderSize):

            try:
                re = LRU[len(LRU)-1]
                if (len(re) == 5 and os.path.isdir(f"app/reduced_maps/coords/{re[0]}/{re[1]}/{re[2]}/{re[3]}/{re[4]}")):
                    shutil.rmtree(f"app/reduced_maps/coords/{re[0]}/{re[1]}/{re[2]}/{re[3]}/{re[4]}")
                elif(len(re) == 2 and os.path.isdir(f"app/reduced_maps/cities/{re[0]}/{re[1]}")):
                    shutil.rmtree(f"app/reduced_maps/cities/{re[0]}/{re[1]}")
                del LRU[len(LRU)-1]
            except:
                print("ERROR Deleteing map File")
        with open("lru.txt", "wb") as fp:   #Pickling
            pickle.dump(LRU, fp)
    return

def pipeline(location, level, cityName = None):
    '''The main method that pipelines the process of converting and shrinking map requests

    Parameters:
        location(list): A list of coordinates[minLat, minLon, maxLat, maxLon] of bounding box
        level(string): The level of detail the map being requested should be
        cityName(string): The name of a requested city if given, otherwise is set to None

    Returns:
        string: json data of the map requested with filters and sizing completed
    '''

    filename = map_update.mapfile()


    #Checks input for name or list
    if cityName is not None :
        location[0] = float(location[0]) #minLat
        location[1] = float(location[1]) #minLon
        location[2] = float(location[2]) #maxLat
        location[3] = float(location[3]) #maxLon
        dir = f"app/reduced_maps/cities/{cityName}/{level}"
        if (os.path.isfile(f"{dir}/map_data.json")):
            app_log.info(f"{cityName} map has already been generated")
            f = open(f"{dir}/map_data.json")
            data = json.load(f)
            f.close()
            lruUpdate(location, level, cityName)
            return  json.dumps(data, sort_keys = False, indent = 2)



    elif cityName == None:
        #Used to remove extra trailing zeros to prevent duplicates
        #might be redundent
        location[0] = float(location[0]) #minLat
        location[1] = float(location[1]) #minLon
        location[2] = float(location[2]) #maxLat
        location[3] = float(location[3]) #maxLon

        # minLat / minLon / maxLat / maxLon
        dir = f"app/reduced_maps/coords/{location[0]}/{location[1]}/{location[2]}/{location[3]}/{level}"
        if (os.path.isfile(f"{dir}/map_data.json")):
            app_log.info("The map was found in the servers map storage")
            f = open(f'{dir}/map_data.json')
            data = json.load(f)
            f.close()
            lruUpdate(location, level, cityName)
            return  json.dumps(data, sort_keys = False, indent = 2) #returns map data from storage


    if (map_size(location, level)):
        app_log.info("Map bounds outside of max map size allowed")
        return "MAP BOUNDING SIZE IS TOO LARGE"

    start_time = time.time() #timer to determine map process time

    #Map Convert Call, converts the large NA map to that of the bounding box
    o5m = call_convert2(str(filename), location)

    #Map Filter Call, filters out any data that is not required withing the level requested
    filename = call_filter(o5m, level)


    #Starts using osm_to_adj.py
    try:
        #Sets memory constraints on the program to prevent memory crashes
        soft, hard = resource.getrlimit(resource.RLIMIT_AS)
        resource.setrlimit(resource.RLIMIT_AS, (get_memory() * 1024 * memPercent, hard))
        app_log.info(f"Starting OSM to Adj Convert on {filename}")


        adj_start_time = time.time() #timer to determine run time of osm_to_adj
        test2 = osm_to_adj.main(filename, 4, cityName) #reduces the number of nodes in map file
        app_log.info("OSM to Adj complete in: : %s" % (time.time() - adj_start_time))

        #Save map data to server storage
        os.makedirs(dir)
        with open(f"{dir}/map_data.json", 'w') as x:
            json.dump(test2, x, indent=4)
    except MemoryError:
        app_log.exception(f"Memory Exception occurred while processing: {dir}")

    #Resets memory limit
    soft, hard = resource.getrlimit(resource.RLIMIT_AS)
    resource.setrlimit(resource.RLIMIT_AS, (soft, hard))

    #Generates hash file for recently created map
    try:
        md5_hash = hashlib.md5()
        with open(f"{dir}/map_data.json","rb") as f:
            # Read and update hash string value in blocks of 4K
            for byte_block in iter(lambda: f.read(4096),b""):
                md5_hash.update(byte_block)
            app_log.info("Hash: " + md5_hash.hexdigest())
        with open(f"{dir}/hash.txt", "w") as h:
            h.write(md5_hash.hexdigest())
    except:
        app_log.exception("Hashing error occured")

    #removes temporary files generated while generating map
    os.remove(o5m)
    os.remove(filename)

    lruUpdate(location, level, cityName)

    ti = (time.time() - start_time)
    app_log.info(f"Map file created with bounds: {location} in {ti} seconds")
    response = json.dumps(test2, sort_keys = False, indent = 2)
    return response







def updated_pipeline(bbox, level):
    map_dir = f"app/reduced_maps/{bbox[0]}/{bbox[1]}/{bbox[2]}/{bbox[3]}/{level}"
    filename = map_update.mapfile()

    # Checks if map is already generated
    if (os.path.isfile(f"{map_dir}/map_data.json")):
            app_log.info(f"Map has already been generated")
            f = open(f"{map_dir}/map_data.json")
            data = json.load(f)
            f.close()
            lruUpdate(bbox, level)
            return  json.dumps(data, sort_keys = False, indent = 2)


    # If map does not exsist

    # Checks Bounds for too large maps
    if (map_size(bbox, level)):
        app_log.info("Map bounds outside of max map size allowed")
        return "MAP BOUNDING SIZE IS TOO LARGE"



    #CONVERT MAPS

    #Map Convert Call, converts the large NA map to that of the bounding box
    start_time = time.time()
    o5m = call_convert(str(filename), bbox)
    filename = call_filter(o5m, level)

    #Starts using osm_to_adj.py
    try:
        #Sets memory constraints on the program to prevent memory crashes
        soft, hard = resource.getrlimit(resource.RLIMIT_AS)
        resource.setrlimit(resource.RLIMIT_AS, (get_memory() * 1024 * memPercent, hard))
        app_log.info(f"Starting OSM to Adj Convert on {filename}")


        adj_start_time = time.time() #timer to determine run time of osm_to_adj
        test2 = osm_to_adj.main(filename, 4) #reduces the number of nodes in map file
        app_log.info("OSM to Adj complete in: : %s" % (time.time() - adj_start_time))

        #Save map data to server storage
        os.makedirs(map_dir)
        with open(f"{map_dir}/map_data.json", 'w') as x:
            json.dump(test2, x, indent=4)
    except MemoryError:
        app_log.exception(f"Memory Exception occurred while processing: {dir}")

    #Resets memory limit
    soft, hard = resource.getrlimit(resource.RLIMIT_AS)
    resource.setrlimit(resource.RLIMIT_AS, (soft, hard))


    #Generates hash file for recently created map
    try:
        md5_hash = hashlib.md5()
        with open(f"{map_dir}/map_data.json","rb") as f:
            # Read and update hash string value in blocks of 4K
            for byte_block in iter(lambda: f.read(4096),b""):
                md5_hash.update(byte_block)
            app_log.info("Hash: " + md5_hash.hexdigest())
        with open(f"{map_dir}/hash.txt", "w") as h:
            h.write(md5_hash.hexdigest())
    except:
        app_log.exception("Hashing error occured")

    #removes temporary files generated while generating map
    os.remove(o5m)
    os.remove(filename)

    lruUpdate(bbox, level)

    ti = (time.time() - start_time)
    app_log.info(f"Map file created with bounds: {bbox} in {ti} seconds")
    response = json.dumps(test2, sort_keys = False, indent = 2)
    return response


@app.cli.command('wipe', help='Wipe the cache (but not the maps)')
def wipe_cache():
    map_update.flush_map_cache()

@app.cli.command('update', help='Force the update of the maps (and flush the cache)') 
def redownload_primary_maps():
    try:
        map_update.force_map_update()
    except:
        pass

#Creates a background scheduled task for the map update method
sched = BackgroundScheduler()
sched.daemonic = True
sched.start()

sched.add_job(map_update.update, 'cron', day='1st tue', hour='2', misfire_grace_time=None)

sched.print_jobs()


#logging.basicConfig(filename='log.log',format='%(asctime)s %(message)s', level=logging.DEBUG)

format = logging.Formatter('%(asctime)s %(message)s')
logFile = 'log.log'
#my_handler = RotatingFileHandler(logFile, mode='a', maxBytes=5*1024*1024,
#                                 backupCount=2, encoding=None, delay=0)
my_handler = StreamHandler()
my_handler.setFormatter(format)
my_handler.setLevel(logging.INFO)

app_log = logging.getLogger('root')
app_log.setLevel(logging.DEBUG)

app_log.addHandler(my_handler)

map_update.init(app_log)

try:
    with open("lru.txt", "rb") as fp:
        LRU = pickle.load(fp)
except:
    pass




#default folder size (GB)
maxMapFolderSize = (os.getenv('FOLDER_SIZE'))
if maxMapFolderSize is None:
    maxMapFolderSize = 1*1024*1024*1024
else:
    maxMapFolderSize = maxMapFolderSize  * 1024 * 1024 * 1024
#default memory limit
memPercent = os.getenv('MEMORY_LIMIT')
if memPercent is None:
    memPercent = .85

map_update.check_for_emergency_map_update()
