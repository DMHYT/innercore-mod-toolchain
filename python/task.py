import os
import os.path
import sys
import time
import urllib.request as request
import shutil
import zipfile

from utils import ensure_directory, ensure_file_dir, clear_directory, copy_file, copy_directory

make_config = None
registered_tasks = {}
locked_tasks = {}
devnull = open(os.devnull, "w")


def copytree(src, dst, symlinks=False, ignore=None):
    if not os.path.exists(src) or os.path.isfile(src):
        raise Exception()
    for item in os.listdir(src):
        s = os.path.join(src, item)
        d = os.path.join(dst, item)
        if os.path.isdir(s):
            if not os.path.exists(d):
                os.mkdir(d)
            copytree(s, d, symlinks, ignore)
        else:
            shutil.copy2(s, d)


def get_make_config():
	global make_config
	if make_config is None:
		from make_config import make_config as config
		make_config = config
	return make_config


def lock_task(name, silent=True):
	path = get_make_config().get_path(f"toolchain/build/lock/{name}.lock")
	ensure_file_dir(path)
	await_message = False

	if os.path.exists(path):
		while True:
			try:
				if os.path.exists(path):
					os.remove(path)
				break
			except IOError as _:
				if not await_message:
					await_message = True
					if not silent:
						sys.stdout.write(f"task {name} is locked by another process, waiting for it to unlock.")
					if name in locked_tasks:
						error("ERROR: dead lock detected", code=-2)
				if not silent:
					sys.stdout.write(".")
					sys.stdout.flush()
				time.sleep(0.5)
	if await_message:
		if not silent:
			print("")
	open(path, "tw").close()
	locked_tasks[name] = open(path, "a")


def unlock_task(name):
	if name in locked_tasks:
		locked_tasks[name].close()
		del locked_tasks[name]
	path = get_make_config().get_path(f"toolchain/build/lock/{name}.lock")
	if os.path.isfile(path):
		os.remove(path)


def unlock_all_tasks():
	for name in list(locked_tasks.keys()):
		unlock_task(name)


def task(name, lock=None):
	if lock is None:
		lock = []

	def decorator(func):
		def caller(*args, **kwargs):
			lock_task(name, silent=False)
			for lock_name in lock:
				lock_task(lock_name, silent=False)
			os.system("color")
			print(f"\033[92m> executing task: {name}\033[0m")
			task_result = func(*args, **kwargs)
			unlock_task(name)
			for lock_name in lock:
				unlock_task(lock_name)
			return task_result

		registered_tasks[name] = caller
		return caller

	return decorator


@task("compileNativeDebug", lock=["native", "cleanup", "push"])
def task_compile_native_debug():
	abi = get_make_config().get_value("make.debugAbi", None)
	if abi is None:
		abi = "armeabi-v7a"
		print(f"WARNING: no make.debugAbi value in config, using {abi} as default")
	from native.native_build import compile_all_using_make_config
	return compile_all_using_make_config([abi])


@task("compileNativeRelease", lock=["native", "cleanup", "push"])
def task_compile_native_release():
	abis = get_make_config().get_value("make.abis", [])
	if abis is None or not isinstance(abis, list) or len(abis) == 0:
		error(f"ERROR: no make.abis value in config")
	from native.native_build import compile_all_using_make_config
	return compile_all_using_make_config(abis)


@task("clearGradleCache", lock=["java", "cleanup", "push"])
def task_clear_gradle_cache():
	from java.java_build import clear_gradle_cache_directory
	return clear_gradle_cache_directory()


@task("compileJavaDebug", lock=["java", "cleanup", "push"])
def task_compile_java_debug():
	from java.java_build import compile_all_using_make_config
	return compile_all_using_make_config()


@task("compileJavaRelease", lock=["java", "cleanup", "push"])
def task_compile_java_release():
	from java.java_build import compile_all_using_make_config
	return compile_all_using_make_config()


@task("buildScripts", lock=["script", "cleanup", "push"])
def task_build_scripts():
	from script_build import build_all_scripts
	return build_all_scripts()


@task("buildResources", lock=["resource", "cleanup", "push"])
def task_resources():
	from script_build import build_all_resources
	return build_all_resources()


@task("buildInfo", lock=["cleanup", "push"])
def task_build_info():
	import json
	config = get_make_config()
	with open(config.get_path("output/mod.info"), "w") as info_file:
		info = dict(config.get_value("global.info", fallback={"name": "No was provided"}))
		if "icon" in info:
			del info["icon"]
		info_file.write(json.dumps(info, indent=" " * 4))
	icon_path = config.get_value("global.info.icon")
	if icon_path is not None:
		copy_file(config.get_path(icon_path),
				  config.get_path("output/mod_icon.png"))
	return 0


@task("buildAdditional", lock=["cleanup", "push"])
def task_build_additional():
	overall_result = 0
	for additional_dir in get_make_config().get_value("additional", fallback=[]):
		if "source" in additional_dir and "targetDir" in additional_dir:
			for additional_path in get_make_config().get_paths(additional_dir["source"]):
				if not os.path.exists(additional_path):
					print("non existing additional path: " + additional_path)
					overall_result = 1
					break
				target = get_make_config().get_path(os.path.join(
					"output",
					additional_dir["targetDir"],
					os.path.basename(additional_path)
				))
				if os.path.isdir(additional_path):
					copy_directory(additional_path, target)
				else:
					ensure_file_dir(target)
					copy_file(additional_path, target)
	return overall_result


@task("pushEverything", lock=["push"])
def task_push_everything():
	from push import push
	return push(get_make_config().get_path("output"))


@task("clearOutput", lock=["assemble", "push", "native", "java"])
def task_clear_output():
	clear_directory(get_make_config().get_path("output"))
	return 0


@task("excludeDirectories", lock=["push", "assemble", "native", "java"])
def task_exclude_directories():
	config = get_make_config()
	for path in config.get_value("make.excludeFromRelease", []):
		for exclude in config.get_paths(os.path.join("output", path)):
			if os.path.isdir(exclude):
				clear_directory(exclude)
			elif os.path.isfile(exclude):
				os.remove(exclude)
	return 0


@task("buildPackage", lock=["push", "assemble", "native", "java"])
def task_build_package():
	import shutil
	output_dir = get_make_config().get_path("output")
	output_file = get_make_config().get_path("mod.icmod")
	output_file_tmp = get_make_config().get_path("toolchain/build/mod.zip")
	ensure_directory(output_dir)
	ensure_file_dir(output_file_tmp)
	if os.path.isfile(output_file):
		os.remove(output_file)
	if os.path.isfile(output_file_tmp):
		os.remove(output_file_tmp)
	shutil.make_archive(output_file_tmp[:-4], 'zip', output_dir)
	os.rename(output_file_tmp, output_file)
	return 0


@task("launchHorizon")
def task_launch_horizon():
	from subprocess import call
	call([make_config.get_adb(), "shell", "touch", "/storage/emulated/0/games/horizon/.flag_auto_launch"], stdout=devnull, stderr=devnull)
	result = call([make_config.get_adb(), "shell", "monkey", "-p", "com.zheka.horizon", "-c", "android.intent.category.LAUNCHER", "1"], stdout=devnull, stderr=devnull)
	if result != 0:
		print("\033[91mno devices/emulators found, try to use task \"Connect to ADB\"\033[0m")
	return 0

@task("stopHorizon")
def stop_horizon():
	from subprocess import call
	result = call([make_config.get_adb(), "shell", "am", "force-stop", "com.zheka.horizon"], stdout=devnull, stderr=devnull)
	if result != 0:
		print("\033[91mno devices/emulators found, try to use task \"Connect to ADB\"\033[0m")
	return result
	
@task("loadDocs")
def task_load_docs():
	def _load(name, fromDocs=True, fileName=None):
		url = ("https://docs.mineprogramming.org/headers/" + name + ".d.ts") if fromDocs else name
		response = request.urlopen(url)
		content = response.read().decode('utf-8')
		if fileName == None:
			fileName = name
		with open(make_config.get_path("toolchain/declarations/" + fileName + ".d.ts"), 'w') as docs:
			docs.write(content)
		print(fileName + ".d.ts downloaded")
	print("downloading ts declarations...")
	_load("core-engine")
	_load("android")
	_load("android-declarations")
	_load("https://raw.githubusercontent.com/DMHYT/innercore-development-cloud/main/preloader.d.ts", fromDocs=False, fileName="preloader")
	print("complete!")
	return 0

@task("loadJavaDependencies")
def task_load_java_dependencies():
	def _load(name):
		url = "https://github.com/DMHYT/innercore-development-cloud/blob/main/classpath/" + name + ".jar?raw=true"
		local_path = make_config.get_path("toolchain/classpath/" + name + ".jar")
		request.urlretrieve(url, filename=local_path)
		print(name + ".jar downloaded")
	print("downloading java dependencies...")
	_load("android-support-multidex")
	_load("android-support-v4")
	_load("android-support-v7-recyclerview")
	_load("android")
	_load("classes-dex2jar")
	_load("classes2-dex2jar")
	_load("horizon-classes")
	_load("rhino-1.7.7")
	print("complete!")
	return 0

@task("loadAdbAndBin")
def task_load_adb_and_bin():
	print("downloading ADB and java build tools...")
	toolchain_path = make_config.get_path("toolchain")
	for archive_name in ["adb", "bin"]:
		d = os.path.join(toolchain_path, archive_name)
		if os.path.exists(d):
			os.remove(d) if os.path.isfile(d) else shutil.rmtree(d)
		dz = d + ".zip"
		if os.path.exists(dz):
			os.remove(dz) if os.path.isfile(dz) else shutil.rmtree(dz)
		archive_fname = archive_name + ".zip"
		url = "https://github.com/DMHYT/innercore-development-cloud/blob/main/" + archive_fname + "?raw=true"
		archive_path = os.path.join(toolchain_path, archive_fname)
		request.urlretrieve(url, filename=archive_path)
		print(archive_fname + " downloaded")
		with zipfile.ZipFile(archive_path, 'r') as archive:
			archive.extractall(toolchain_path)
			print(archive_fname + " extracted to toolchain/" + archive_name + "/")
		os.remove(archive_path)
		print(archive_fname + " removed")
	print("complete!")
	return 0

@task("downloadICHeaders")
def task_download_innercore_headers():
	try:
		from zipfile import ZipFile
		print("downloading innercore native headers...")
		url = "https://codeload.github.com/DMHYT/innercore-native-headers/zip/main"
		local_path = make_config.get_path("toolchain/stdincludes/archive.zip")
		request.urlretrieve(url, filename=local_path)
		with ZipFile(local_path, 'r') as zipp:
			zipp.extractall(path=local_path[:-12])
		dist = make_config.get_path("toolchain/stdincludes")
		shit = os.path.join(dist, "innercore-native-headers-main")
		dist2 = os.path.join(dist, "horizon")
		if not os.path.exists(dist2):
			os.mkdir(dist2)
		copytree(os.path.join(shit, "horizon"), dist2)
		shutil.rmtree(shit)
		os.remove(local_path)
		print("complete!")
	except: pass
	return 0

@task("downloadGnustlHeaders")
def task_download_gnustl_headers():
	try:
		from zipfile import ZipFile
		print("downloading gnustl shared headers...")
		url = "https://codeload.github.com/zheka2304/gnustl-shared-headers/zip/master"
		local_path = make_config.get_path("toolchain/stdincludes/gnustl/archive.zip")
		request.urlretrieve(url, filename=local_path)
		with ZipFile(local_path, 'r') as zipp:
			zipp.extractall(path=local_path[:-12])
		dist = make_config.get_path("toolchain/stdincludes/gnustl")
		shit = os.path.join(dist, "gnustl-shared-headers-master")
		stl = os.path.join(dist, "stl")
		if not os.path.exists(stl):
			os.mkdir(stl)
		copytree(os.path.join(shit, "stl"), stl)
		shutil.rmtree(shit)
		os.remove(local_path)
		print("complete!")
	except: pass
	return 0

@task("downloadNdkIfNeeded")
def task_download_ndk_if_needed():
	from native.native_setup import require_compiler_executable
	print("preparing ndk...")
	require_compiler_executable(arch="arm", install_if_required=True)
	print("ndk was locally downloaded successfully!")
	return 0

@task("cleanupOutput")
def task_cleanup_output():
	def clean(p):
		_walk = lambda: [f for f in list(os.walk(p))[1:] if os.path.exists(f[0])]
		for folder in _walk():
			if len(folder[2]) > 0:
				continue
			if len(folder[1]) > 0:
				for subfolder in folder[1]:
					clean(os.path.join(folder[0], subfolder))
				for folder2 in _walk():
					if len(folder2[1]) == 0 and len(folder2[2]) == 0:
						os.rmdir(folder2[0])
	path = make_config.get_path("output")
	if os.path.exists(path):
		clean(path)
	return 0

@task("updateIncludes")
def task_update_includes():
	from functools import cmp_to_key
	from mod_structure import mod_structure
	from includes import Includes, temp_directory
	def libraries_first(a, b):
		la = a["type"] == "library"
		lb = b["type"] == "library"
		if la == lb:
			return 0
		elif la:
			return -1
		else:
			return 1
	sources = sorted(make_config.get_value("sources", fallback=[]), key=cmp_to_key(libraries_first))
	for item in sources:
		_source = item["source"]
		_target = item["target"] if "target" in item else None
		_type = item["type"]
		if _type not in ("main", "library", "preloader"):
			print(f"skipped invalid source with type {_type}")
			continue
		for source_path in make_config.get_paths(_source):
			if not os.path.exists(source_path):
				print(f"skipped non-existing source path {_source}")
				continue
			target_path = _target if _target is not None else f"{os.path.splitext(os.path.basename(source_path))[0]}.js"
			declare = {
				"sourceType": {
					"main": "mod",
					"launcher": "launcher",
					"preloader": "preloader",
					"library": "library"
				}[_type]
			}
			if "api" in item:
				declare["api"] = item["api"]
			try:
				dot_index = target_path.rindex(".")
				target_path = target_path[:dot_index] + "{}" + target_path[dot_index:]
			except ValueError:
				target_path += "{}"
			mod_structure.update_build_config_list("compile")
			incl = Includes.invalidate(source_path)
			incl.create_tsconfig(os.path.join(temp_directory, os.path.basename(target_path)))
	return 0

@task("connectToADB")
def task_connect_to_adb():
	import re

	ip = None
	port = None
	pattern = re.compile(r"(\d{1,3}.\d{1,3}.\d{1,3}.\d{1,3}):(\d{4})")
	for arg in sys.argv:
		match = pattern.search(arg)
		if match:
			ip = match[0]
			port = match[1]

	if ip is None:
		print("incorrect IP-address")
		return 1

	print(f"connecting to {ip}")

	from subprocess import call
	call([make_config.get_adb(), "disconnect"], stdout=devnull, stderr=devnull)
	call([make_config.get_adb(), "tcpip", port], stdout=devnull, stderr=devnull)
	result = call([make_config.get_adb(), "connect", ip])
	return result


@task("cleanup")
def task_cleanup():
	config = get_make_config()
	clear_directory(config.get_path("toolchain/build/gcc"))
	clear_directory(config.get_path("toolchain/build/gradle"))
	clear_directory(config.get_path("toolchain/build/project"))

#                               not working
#     import java.java_build
#     java.java_build.cleanup_gradle_scripts()
	return 0


def error(message, code=-1):
	sys.stderr.write(message + "\n")
	unlock_all_tasks()
#    input("Press enter to continue...")
	exit(code)


if __name__ == '__main__':
	if len(sys.argv[1:]) > 0:
		for task_name in sys.argv[1:]:
			if task_name in registered_tasks:
				try:
					result = registered_tasks[task_name]()
					if result != 0:
						error(f"task {task_name} failed with result {result}", code=result)
				except BaseException as err:
					if isinstance(err, SystemExit):
						raise err

					import traceback
					traceback.print_exc()
					error(f"task {task_name} failed with above error")
#            else:
#                error(f"no such task: {task_name}")
	else:
		error("no tasks to execute")
	unlock_all_tasks()
