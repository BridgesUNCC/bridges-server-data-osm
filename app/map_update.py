import wget
import subprocess
import os
import logging
import json
from datetime import *
import time
import shutil

divider = "-----------------------------------------------------------------"


app_log = None
path_to_mapfile=None
path_to_amenityfile=None

def mapfile():
    return path_to_mapfile

def amenityfile():
    return path_to_amenityfile


def init(al):
    ''' initialize the map_update module
    Param:
      al: app logger
    '''
    global app_log
    app_log = al

    global path_to_amenityfile
    global path_to_mapfile
    
    #figuring out the correct map location
    with open("app/update.json", "r") as f:
        loaded = json.load(f)
        
        for sub in loaded["maps"]:
            map_title = sub["map"]

            path_to_mapfile = f"app/map_files/{sub['file_name']}" 
            path_to_amenityfile = f"app/map_files/amenity-{sub['file_name']}" 

    

def download_map(url, outfolder):
    """Uses wget to attempt downloading a map url

    Parameters:
    url(str): String of the URL that the map download is located at

    Returns:
    string: String of the directory location of the map downloaded

    """
    try:
        filename = wget.download(url, out=f"{outfolder}/")
        app_log.info("Map Download Complete")
    except:
        print("Error downloading map")
        app_log.exception("Exception occurred while downloading map")
        raise
    return filename


def flush_map_cache():
    #Clears the saved coordinate maps on update call
    if os.path.isdir("app/reduced_maps"):
        shutil.rmtree("app/reduced_maps")
            
    os.makedirs("app/reduced_maps/coords", exist_ok=True)
    os.makedirs("app/reduced_maps/cities", exist_ok=True)

    try:
        os.remove("lru.txt")
    except:
        pass #If the file did not already exist, an eexception is raised, but is benign

# with new install code, this no longer seem necessary
#    f = open("app/reduced_maps/coords/.gitkeep", 'w')
#    f.close()
#    f = open("app/reduced_maps/cities/.gitkeep", 'w')
#    f.close()


def install_file(src: str, dest: str):
    '''Install file at path src into path dest.
    This function creates the directory for dest if necessary.
    This function moves the src file to path dest.
    If there is already a file called dest, that file is overwritten.
    '''
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    shutil.move(src, dest)
    
def update():
    '''Updates and reduces the root map file'''

    filter_command = '--keep=\"amenity= or aeroway=\" --drop-version --ignore-dependencies'
    map_convert_command = '--keep=\"highway=motorway =trunk =primary =secondary =tertiary =unclassified =residential =primary_link =secondary_link =tertiary_link =trunk_link =living_street =motorway_link =path =footway =cycleway \" --drop-version'
    
    tempfolder = "app/map_files/download" #This folder will be both created AND destroyed

    try:
        flush_map_cache()
    except Exception as e:
        app_log.exception("Error flushing map cache. Probably non critical:")
        app_log.exception(e)                

    
    try:
        with open("app/update.json", "r") as f:
            print("Updating maps...")
            app_log.info(f"{divider}")
            app_log.info(f"Updating map...")
            loaded = json.load(f)
            if not os.path.isdir(tempfolder):
                os.mkdir(tempfolder)
            
            for sub in loaded["maps"]:
                d = datetime.today()
                try:
                    map_title = sub["map"]

                    app_log.info(f"Downloading {map_title} map... (Step 1/7)")
                    download_map(sub["url"], tempfolder)

                    file_name = sub["file_name"]
                    og_map_path = f"{tempfolder}/{file_name}"
                    uncompressed_map_path = f"{tempfolder}/o5m_main.o5m"
                    uncompressed_amenity_path = f"{tempfolder}/filteredTemp.o5m"
                    uncompressed_filtered_map_path = f"{tempfolder}/mainTemp.o5m"

                    app_log.info("Converting maps... (step 2/7)")
                    command  = (f"./app/osm_converts/osmconvert64 {og_map_path} -o={uncompressed_map_path}")
                    subprocess.run([command], shell=True, check=True)
                    

                    # #saving downloaded maps
                    # We don't need to
                    # os.mkdir(f"{tempfolder}/temp")
                    # os.rename(f"{tempfolder}/" + sub["file_name"], "{tempfolder}/temp/" + sub["file_name"])

                    app_log.info("Filtering amenity maps... (step 3/7)")
                    command = f"./app/osm_converts/osmfilter {uncompressed_map_path} {filter_command} -o={uncompressed_amenity_path}"
                    subprocess.run([command], shell=True, check=True)


                    app_log.info("Filtering main maps... (step 4/7)")
                    command = f"./app/osm_converts/osmfilter {uncompressed_map_path} {map_convert_command} -o={uncompressed_filtered_map_path}"
                    subprocess.run([command], shell=True, check=True)

                    app_log.info("Converting main maps... (step 5/7)")
                    command  = (f"./app/osm_converts/osmconvert64 {uncompressed_filtered_map_path} -o={tempfolder}/{file_name}")
                    subprocess.run([command], shell=True, check=True)

                    app_log.info("Converting amenity maps... (step 6/7)")
                    command  = (f"./app/osm_converts/osmconvert64 {uncompressed_amenity_path} -o={tempfolder}/amenity-{file_name}")
                    subprocess.run([command], shell=True, check=True)

                    #os.remove("app/o5m_main.o5m")
                    #os.remove("app/mainTemp.o5m")
                    #os.remove("app/filteredTemp.o5m")

                    app_log.info("Installing maps (Step 7/7)")
                    install_file(f"{tempfolder}/{file_name}", f"app/map_files/{sub['file_name']}")
                    install_file(f"{tempfolder}/amenity-{file_name}", f"app/map_files/amenity-{sub['file_name']}")

                    with open("app/update.json", 'w') as f:
                        sub["last-updated"] = date.today().strftime("%Y%m%d")
                        json.dump(loaded, f, indent=4)

                except Exception as e:
                    app_log.exception(f"Exception occured while updating map {map_title}")
                    app_log.exception(e)
                
            app_log.info("Clearing out temp files")
            shutil.rmtree(f"{tempfolder}")

            
    except Exception as e:
        app_log.exception(e)




# checks whether the map file is there, trigger immediate update otherwise
def check_for_emergency_map_update():
    with open("app/update.json", "r") as f:
        loaded = json.load(f)

        for sub in loaded["maps"]:
            map_title = sub["map"]

            mapFilename = f"app/map_files/{sub['file_name']}" 
            amenityFilename = f"app/map_files/amenity-{sub['file_name']}" 

            if (not os.path.isfile(mapFilename)) or (not os.path.isfile(amenityFilename)):
                print("Map file not found. Emergency map update!")
                update()

def force_map_update():
    app_log.info("Forcing map updates")
    shutil.rmtree('app/map_files')
    os.mkdir('app/map_files')
    update()
