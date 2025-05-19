#!/usr/bin/python3

import sys
import os
import json
import urllib.request

API_KEY = "123456"
HOST = "http://192.168.8.23:8002"
#mapping is category: {source_path: target_path}
category_mapping = {
    "Unprocessed Isos": {
        "/mnt/nfs/mauga/downloads/torrents/Unprocessed Linux Isos": "/mnt/nfs/mauga/isos"
        },
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


def copy_file(source_path, target_path):
        make_post_request("{}/api/files/copy".format(HOST), json.dumps({"sourcePath": source_path, "targetPath": target_path}))


if __name__ == "__main__":
    try:
        (script_name, torrent_name, category, tags, content_path, root_path, save_path, number_of_files, torrent_size, current_tracker, info_hash_v1, info_hash_v2, torrent_id) = sys.argv
        print("Torrent Name:", torrent_name)
        print("Category:", category)
        print("Tags:", tags)
        print("Content Path:", content_path)
        print("Root Path:", root_path)
        print("Save Path:", save_path)
        print("Number of files:", number_of_files)
        print("Torrent size:", torrent_size)
        print("Current tracker:", current_tracker)
        print("Hash_v1:", info_hash_v1)
        print("Hash_v2:", info_hash_v2)
        print("Torrent id:", torrent_id)
    except:
        print("No commandline parameters found")
        sys.exit(1)


    map = category_mapping.get(category)

    if map is not None:
        source = list(map.keys())[0] + "/" + torrent_name
        target = list(map.values())[0] + "/" + torrent_name
        print("Source:", source)
        print("Target:", target)
        copy_file(source, target)