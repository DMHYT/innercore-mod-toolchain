import os
from os.path import join, exists, isdir, basename, isfile
import sys
import json
from utils import clear_directory, remove_xml_whitespace
import zipfile
from make_config import make_config as make


def setup_mod_info(make_file):
	name = input("Enter project name: ")
	author = input("Enter author name: ")
	version = input("Enter project version [1.0]: ")
	description = input("Enter project description: ")
	isClientOnly = input("Will your mod be client side [y/N]: ")
	if isClientOnly == "y":
		isClientOnly = True
	else: isClientOnly = False
	if version == "":
		version = "1.0"
	make_file["global"]["info"] = {
		"name": name,
		"author": author,
		"version": version,
		"description": description,
		"clientside": isClientOnly
	}


def setup_launcher_js(make_file):
	tab = "    "
	launcher_contents = "ConfigureMultiplayer({\n" + tab + "\
		name: \"" + make_file["global"]["info"]["name"] + "\",\n" + tab + "\
		version: \"" + make_file["global"]["info"]["version"] + "\",\n" + tab +"\
		isClientOnly: " + ("true" if make_file["global"]["info"]["clientside"] else "false") + "\n});\nLaunch();"
	with open(make.get_path("src/launcher.js"), 'w') as file:
		file.write(launcher_contents)


def init_java_and_native(make_file, directory):
	src_dir = join(directory, "src")

	sample_native_module = join(src_dir, "native", "sample")
	if not exists(sample_native_module):
		print("native sample module is unavailable")

	else:
		res = input("Do you want to initialize a new native directory? [y/N]: ")
		if res.lower() == 'y':
			module_name = input("Enter the new native module name [sample]: ")
			if module_name != "":
				os.rename(sample_native_module,
					join(src_dir, "native", module_name))
		else:
			if(isdir(sample_native_module)):
				clear_directory(sample_native_module)


	sample_java_archive = join(src_dir, "java.zip")
	if(not exists(sample_java_archive)):
		print("java sample module is unavailable")
	else: 
		res = input("Do you want to initialize a new java directory? [y/N]: ")
		if res.lower() == 'y':
			module_name = input("Enter the new java module name [sample]: ")
			if module_name == "":
				module_name = "sample"

			with zipfile.ZipFile(sample_java_archive, 'r') as zip_ref:
				zip_ref.extractall(join(src_dir))

			os.rename(join(src_dir, "java", "sample"),
				join(src_dir, "java", module_name))
			
			# write info to .classpath
			import xml.etree.ElementTree as etree
			import xml.dom.minidom as minidom
			classpath = join(directory, ".classpath")
			tree = etree.parse(classpath).getroot()
			src_entry = etree.SubElement(tree, "classpathentry")
			src_entry.set("kind", "src")
			src_entry.set("path", "src/java/" + module_name + "/src")
			xmlstr = etree.tostring(tree, encoding="utf-8", xml_declaration=True)
			xmldom = minidom.parseString(xmlstr)
			remove_xml_whitespace(xmldom)
			xmlstr = xmldom.toprettyxml(encoding="utf-8").decode("utf-8")
			with open(classpath, 'w', encoding="utf-8") as classpath_file:
				classpath_file.write(xmlstr)
		if(isfile(sample_java_archive)):
			os.remove(sample_java_archive)


def cleanup_if_required(directory):
	res = input("Do you want to clean up the project? [Y/n]: ")
	if res.lower() == 'n':
		return

	to_remove = [
		"toolchain-setup.py",
		"toolchain-import.py",
		"toolchain.zip"
	]
	for f in to_remove:
		path = join(directory, f)
		if(exists(path)):
			os.remove(path)


def init_directories(directory):
	assets_dir = join(directory, "src", "assets")
	clear_directory(assets_dir)
	os.makedirs(join(assets_dir, "gui"))
	os.makedirs(join(assets_dir, "res", "items-opaque"))
	os.makedirs(join(assets_dir, "res", "terrain-atlas"))
	libs_dir = join(directory, "src", "lib")
	clear_directory(libs_dir)
	os.makedirs(libs_dir)
	os.makedirs(join(directory, "src", "preloader"))
	os.makedirs(join(assets_dir, "resource_packs"))
	os.makedirs(join(assets_dir, "behavior_packs"))
	with(open(join(directory, "src", "dev", "header.js"), "w", encoding="utf-8")) as file:
		file.write("")



def init_adb(make_file, dirname):
	pack_name = input("Enter your pack directory name [Inner_Core]: ")
	if pack_name == "":
		pack_name = "Inner_Core"

	make_file["make"]["pushTo"] = "storage/emulated/0/games/horizon/packs/" + pack_name + "/innercore/mods/" + dirname


print("running project setup script")

destination = sys.argv[1]
make_path = join(destination, "make.json")

if not (exists(make_path)):
	exit("invalid arguments passed to import script, usage: \r\npython setup.py <destination>")

with open(make_path, "r", encoding="utf-8") as make_file:
	make_obj = json.loads(make_file.read())

if destination == '.':
	dirname = basename(os.getcwd())
else: 
	dirname = basename(destination)


init_adb(make_obj, dirname)
print("initializing mod.info")
setup_mod_info(make_obj)
print("initializing required directories")
init_directories(destination)
print("initializing java and native modules")
init_java_and_native(make_obj, destination)
cleanup_if_required(destination)
setup_launcher_js(make_obj)

with open(make_path, "w", encoding="utf-8") as make_file:
	make_file.write(json.dumps(make_obj, indent=" " * 4))

print("project successfully set up")