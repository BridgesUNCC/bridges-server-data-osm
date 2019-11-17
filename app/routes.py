from app import app
from flask import request
import wget
import subprocess
import json
import app.osm_to_adj as osm_to_adj
import os
from datetime import *
import shutil
import sys
import resource
import logging
from logging.handlers import RotatingFileHandler
import time
import hashlib
import pickle
import io
from apscheduler.schedulers.background import BackgroundScheduler
import xml.etree.ElementTree as ET

memPercent = .85 # % of RAM allowed for osm_to_adj.py to use
degreeRound = 4 #number of decimal places to round bounding box coords too
maxMapFolderSize = 1*1024*1024*1024  #change first value to set number of gigabits the map folder should be
LRU = []

default = '--keep=\"highway=motorway =trunk =primary =secondary =tertiary =unclassified =primary_link =secondary_link =tertiary_link =trunk_link =motorway_link\" --drop-version'
map_convert_command = '--keep=\"highway=motorway =trunk =primary =secondary =tertiary =unclassified =primary_link =secondary_link =tertiary_link =trunk_link =living_street =motorway_link =path =footway =cycleway \" --drop-version'
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



'''
NOAA Grid Extraction URL

https://gis.ngdc.noaa.gov/mapviewer-support/wcs-proxy/wcs.groovy?filename=etopo1.xyz&request=getcoverage&version=1.0.0&service=wcs&coverage=etopo1&CRS=EPSG:4326&format=xyz&resx=0.016666666666666667&resy=0.016666666666666667&bbox=-98.08593749997456,36.03133177632377,-88.94531249997696,41.508577297430456
'''



# This takes the output of the server and adds the appropriate headers to make the security team happy
def harden_response(message_str):
    response = app.make_response(message_str)
    response.headers['Content-Security-Policy'] = "default-src 'self'"
    response.headers['X-Frame-Options'] = 'SAMEORIGIN'
    return response

@app.route('/amenity')
def amenity():
    if((request.args['minLat'] is not None) and (request.args['minLon'] is not None) and (request.args['maxLat'] is not None) and (request.args['maxLon'] is not None)):
        try:
            input_Value = [round(float(request.args['minLat']), degreeRound), round(float(request.args['minLon']), degreeRound), round(float(request.args['maxLat']), degreeRound), round(float(request.args['maxLon']), degreeRound)]
            app_log.info(divider)
            app_log.info(f"Requester: {request.remote_addr}")
            app_log.info(f"Script started with Box: {request.args['minLat']}, {request.args['minLon']}, {request.args['maxLat']}, {request.args['maxLon']} bounds")
        except:
            print("System arguments are invalid")
            app_log.exception(f"System arguments invalid {request.args['location']}")
            return harden_response("Invalid arguments")
    
    



    #Check to see if amenity data has already been computed
    dir = f"app/reduced_maps/coords/{input_Value[0]}/{input_Value[1]}/{input_Value[2]}/{input_Value[3]}"
    if (os.path.isfile(f"{dir}/amenity_data.json")):
        app_log.info(f"Amenity data set already generated")
        f = open(f"{dir}/amenity_data.json")
        data = json.load(f)
        f.close()
        return  json.dumps(data, sort_keys = False, indent = 2)



    o5m = call_convert("app/map_files/amenity-north-america-latest.osm.pbf", input_Value)
    filename = callAmenityFilter(o5m, "food")


    tree = ET.parse(filename)
    root = tree.getroot()

    out_nodes = []
    num_val = 0
    for child in root:
        if(child.get('id') == None or child.get('lat') == None or child.get('lon') == None):
            continue
        
        id_val = int(child.get('id'))
        lat = float(child.get('lat'))
        lon = float(child.get('lon'))
        for x in child:
            if (x.attrib.get('k') == 'name'):
                name = x.attrib.get('v') 
            if (x.attrib.get('k') == 'amenity'):
                amenity = x.attrib.get('v')

        if (name == None or amenity == None):
            continue
        num_val += 1
        out_nodes.append([id_val, lat, lon, name, amenity])
    # http://127.0.0.1:5000/amenity?minLon=-80.97006&minLat=35.08092&maxLon=-80.6693&maxLat=35.3457


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
    dir = f"app/reduced_maps/coords/{input_Value[0]}/{input_Value[1]}/{input_Value[2]}/{input_Value[3]}"
    
    try:
        os.makedirs(dir)
    except:
        pass

    with open(f"{dir}/amenity_data.json", 'w') as x:
        json.dump(node, x, indent=4)
    return json.dumps(node)

@app.route('/loc')
def namedInput():
    try:
        input_Value = request.args['location'].lower()
        app_log.info(divider)
        app_log.info(f"Requester: {request.remote_addr}")
        app_log.info(f"Script started with {request.args['location']} parameters")
        if not all(x.isalpha() or x.isspace() for x in input_Value):
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
            return harden_response(pipeline(coords, level, input_Value.lower()))
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

@app.route('/hash')
def hashreturn():
    type = None
    loc = None
    try:
        loc = str(request.args['location']).lower()
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

    try:
        x = request.args['level'].lower()
        if (x == 'motorway' or x == 'trunk' or x == 'primary' or x == 'secondary' or x == 'tertiary' or rx == 'unclassified'):
            level = str(x)
        else:
            level = "default"
    except:
        level = "default"


    if (type == "loc"):
        dir = f"app/reduced_maps/cities/{loc}/{level}"
    elif (type == "coord"):
        dir = f"app/reduced_maps/coords/{input_Value[0]}/{input_Value[1]}/{input_Value[2]}/{input_Value[3]}/{level}"
    else:
        return harden_response(page_not_found())



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
        loaded = json.load(x)
        for city in loaded:
            outStr = outStr + city['city'] + ", " + city['state'] + "</br>"
    return harden_response(outStr)

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

def call_convert(filename, box=[]):
    """Creates a process of the osmconvert, to shrink the map file down to a bounding box as well as change the file type to .o5m

    Parameters:
    filename(str): String of the file path to the map
    box(list): list of longitude and latitude coordinates

    Returns:
    string: String of the directory that the o5m file was generated in

    """

    try:
        bbox = f"-b=\"{box[1]}, {box[0]}, {box[3]}, {box[2]}\""
        command  = (f"app/osm_converts/osmconvert64 " + filename + " " +  bbox + f" -o=app/o5m_Temp.o5m")
    except:
        command  = (f"app/osm_converts/osmconvert64 " + filename + f" -o=app/o5m_Temp.o5m")


    app_log.info(f"Converting {box[0]}, {box[1]}, {box[2]}, {box[3]} map to .o5m")


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
        app_log.info(f"Starting osmfilter on {o5m_filename} with filter command level {level}")
        subprocess.run([command], shell=True)
        app_log.info("Filtering Complete in: %s" % (time.time() - start_time))
    except:
        print("Error while filtering data")
        app_log.exception(f"Exception while filtering data on map: {o5m_filename}")

    return f"app/{area}.xml"

def callAmenityFilter(o5m_filename, filter):

    para = '--keep=\"all amenity'

    if (filter == "food"):
        para= para + "=fast_food =restaurant =cafe =ice_cream =bar"
    elif(filter == "school"):
        para = para + " =college =kindergarten =school =university"

    para = para + "\" --drop-version --ignore-dependencies"

    command = f"app/osm_converts/osmfilter {o5m_filename} " + para + " -o=app/temp2.xml"
    try:
        start_time = time.time()
        app_log.info(f"Starting osmfilter on {o5m_filename} with filter amenity")
        subprocess.run([command], shell=True)
        app_log.info("Filtering Complete in: %s" % (time.time() - start_time))
    except:
        print("Error while filtering data")
        app_log.exception(f"Exception while filtering data on map: {o5m_filename}")

    return f"app/temp2.xml"

def download_map(url):
    """Uses wget to attempt downloading a map url

    Parameters:
    url(str): String of the URL that the map download is located at

    Returns:
    string: String of the directory location of the map downloaded

    """
    try:
        filename = wget.download(url, out="app/map_files/download")
        print("Map Download Complete")
    except:
        print("Error downloading map")
        app_log.exception("Exception occurred while downloading map")
        return
    return filename

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

def update():
    '''Updates and reduces the root map file'''

    filter_command = '--keep=\"all amenity\" --drop-version --ignore-dependencies'

    try:
        with open("app/update.json", "r") as f:
            print("Updating maps...")
            app_log.info(f"{divider}")
            app_log.info(f"Updating map...")
            loaded = json.load(f)
            if not os.path.isdir("app/map_files/download"):
                os.mkdir("app/map_files/download")
            
            for sub in loaded["maps"]:
                d = datetime.today()
                #if (d.weekday() == 1 and int(d.strftime("%d")) < 7 and int(d.strftime("%h")) > 1 and int(d.strftime("%h")) < 3):
                try:
                    map_title = sub["map"]

                    print(f"Downloading {map_title} map...")
                    download_map(sub["url"])
                    sub["last-updated"] = date.today().strftime("%Y%m%d")

                except:
                    print("Error Downloading Map")
                    app_log.exception(f"Exception occured while downloading map {map_title}")
                    break

                with open("app/update.json", 'w') as f:
                    json.dump(loaded, f, indent=4)

                #filters out info before saving
                try:
                    print("Converting maps... (step 1/5)")
                    app_log.info("Converting maps... (step 1/5)")
                    file_name = sub["file_name"]
                    command  = (f"./app/osm_converts/osmconvert64 app/map_files/download/{file_name} -o=app/o5m_main.o5m")
                    subprocess.run([command], shell=True)


                    print("Filtering amenity maps... (step 2/5)")
                    app_log.info("Filtering amenity maps... (step 2/5)")
                    command = f"./app/osm_converts/osmfilter app/o5m_main.o5m " + filter_command + f" -o=app/filteredTemp.o5m"
                    subprocess.run([command], shell=True)

                    print("Filtering main maps... (step 3/5)")
                    app_log.info("Filtering main maps... (step 3/5)")
                    command = f"./app/osm_converts/osmfilter app/o5m_main.o5m " + map_convert_command + f" -o=app/mainTemp.o5m"
                    subprocess.run([command], shell=True)

                    print("Converting main maps... (step 4/5)")
                    app_log.info("Converting main maps... (step 4/5)")
                    os.mkdir("app/map_files/download/temp")
                    os.rename("app/map_files/download/" + sub["file_name"], "app/map_files/download/temp/" + sub["file_name"])
                    command  = (f"./app/osm_converts/osmconvert64 app/mainTemp.o5m -o=app/map_files/download/{file_name}")
                    subprocess.run([command], shell=True)

                    print("Converting amenity maps... (step 5/5)")
                    app_log.info("Converting amenity maps... (step 5/5)")
                    command  = (f"./app/osm_converts/osmconvert64 app/filteredTemp.o5m -o=app/map_files/download/amenity-{file_name}")
                    subprocess.run([command], shell=True)


                    os.remove("app/o5m_main.o5m")
                    os.remove("app/mainTemp.o5m")
                    os.remove("app/filteredTemp.o5m")
                    print("Map convertion done.")
                except:
                    app_log.exception("Converting and filtering error")


                if (os.path.isfile("app/map_files/" + sub["file_name"])):
                    os.remove("app/map_files/" + sub["file_name"])
                os.rename("app/map_files/download/" + sub["file_name"], "app/map_files/" + sub["file_name"])
                os.rename("app/map_files/download/amenity-" + sub["file_name"], "app/map_files/amenity-" + sub["file_name"])

            shutil.rmtree("app/map_files/download")

            #Clears the saved coordinate maps on update call
            if os.path.isdir("app/reduced_maps/coords"):
                shutil.rmtree("app/reduced_maps/coords")

            if os.path.isdir("app/reduced_maps/cities"):
                shutil.rmtree("app/reduced_maps/cities")

            os.mkdir("app/reduced_maps/coords")
            os.mkdir("app/reduced_maps/cities")

            os.remove("lru.txt")

            f = open("app/reduced_maps/coords/.gitkeep", 'w')
            f.close()
            f = open("app/reduced_maps/cities/.gitkeep", 'w')
            f.close()



            print("Maps are up-to-date")
    except Exception as e:
        app_log.exception("Update file read exception" + e)

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
                if (city["city"].lower() == location):
                        minLat = round(city['latitude'] - .1, degreeRound)
                        minLon = round(city['longitude'] - .1, degreeRound)
                        maxLat = round(city['latitude'] + .1, degreeRound)
                        maxLon = round(city['longitude'] + .1, degreeRound)
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

    filename = "app/map_files/north-america-latest.osm.pbf" # NA map file directory


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
    o5m = call_convert(str(filename), location)

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

# checks whether the map file is there, trigger immediate upadte otherwise
def check_for_emergency_map_update():
    filename = "app/map_files/north-america-latest.osm.pbf" # NA map file directory
    amenityFilename = "app/map_files/amenity-north-america-latest.osm.pbf" # NA map file directory

    if (not os.path.isfile(filename)) and (not os.path.isfile(amenityFilename)):
        print("Map file not found. Emergency map update!")
        update()


#Creates a background scheduled task for the map update method
sched = BackgroundScheduler()
sched.daemonic = True
sched.start()

sched.add_job(update, 'cron', day='1st tue', hour='2', misfire_grace_time=None)

sched.print_jobs()

#logging.basicConfig(filename='log.log',format='%(asctime)s %(message)s', level=logging.DEBUG)

format = logging.Formatter('%(asctime)s %(message)s')
logFile = 'log.log'
my_handler = RotatingFileHandler(logFile, mode='a', maxBytes=5*1024*1024,
                                 backupCount=2, encoding=None, delay=0)
my_handler.setFormatter(format)
my_handler.setLevel(logging.INFO)

app_log = logging.getLogger('root')
app_log.setLevel(logging.DEBUG)

app_log.addHandler(my_handler)

try:
    with open("lru.txt", "rb") as fp:
        LRU = pickle.load(fp)
except:
    pass

check_for_emergency_map_update()
