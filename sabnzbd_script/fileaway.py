#!/usr/bin/python3

import sys
import os
import json
import urllib.request

API_KEY = "secret"
HOST = "http://host-192.168.3.2:8002"
#mapping is category: {source_path: target_path}
category_mapping = {
    "iso": {"/share/docker_volumes/sabnzbd/downloads/iso": "/share/nas/iso"},
}


def make_post_request(url, data):
    headers = {
        'Accept': 'application/json',
        'X-API-KEY': API_KEY
    }
    req = urllib.request.Request(url, data=data.encode('utf-8'), method='POST', headers=headers)
    req.add_header('Content-Type', 'application/json')
    try:
        response = urllib.request.urlopen(req)
        if response.getcode() == 200 and response.info().get('Content-Type') == 'application/json':
            print("Request successful")
            print(response.read())
            return response
        else:
            print("Request failed")
    except urllib.error.HTTPError as e:
        print(e.read())
    except urllib.error.URLError as e:
        print("URL Error:", e.reason)
    except Exception as e:
        print("Unknown Error:", e)



def move_file_category(source_path, target_path):
    make_post_request("{}/api/files/move".format(HOST), json.dumps({"sourcePath": source_path, "targetPath": target_path}))


if __name__ == "__main__":
    try:
        (scriptname, directory, orgnzbname, jobname, reportnumber, category, group, postprocstatus, url) = sys.argv
        print("Scriptname:", scriptname)
        print("Directory:", directory)
        print("Orgnzbname:", orgnzbname)
        print("Jobname:", jobname)
        print("Reportnumber:", reportnumber)
        print("Category:", category)
        print("Group:", group)
        print("Postprocstatus:", postprocstatus)
        print("URL:", url)
    except:
        print("No commandline parameters found")
        sys.exit(1)


    map = category_mapping.get(category)

    if map is not None:
        last_directory = os.path.basename(directory)

        source = list(map.keys())[0] + "/" + last_directory
        target = list(map.values())[0] + "/" + last_directory
        move_file_category(source, target)