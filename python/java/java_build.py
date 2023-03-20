
import sys
import os
import subprocess
import json
import zipfile
import hashlib
import shutil

from utils import *
from make_config import make_config


def get_classpath_from_directories(directories):
    classpath = []
    for directory in directories:
        if os.path.isdir(directory):
            for file in os.listdir(directory):
                file = os.path.join(directory, file)
                if os.path.isfile(file):
                    classpath.append(file)
    return classpath


def rebuild_library_cache(directory, library_files, cache_dir):
    directory_name = os.path.basename(directory)
    lib_cache_dir = os.path.join(cache_dir, "d8_lib_cache", directory_name)
    lib_cache_zip = os.path.join(cache_dir, "d8_lib_cache-" + directory_name + ".zip")

    # return [lib_cache_zip]

    print("rebuilding library cache:", directory_name)
    clear_directory(lib_cache_dir)
    ensure_directory(lib_cache_dir)

    for lib_file in library_files:
        print("  extracting library classes:", os.path.basename(lib_file))
        with zipfile.ZipFile(lib_file, "r") as zip_ref:
            zip_ref.extractall(lib_cache_dir)
    print("creating zip...")
    if os.path.isfile(lib_cache_zip):
        os.remove(lib_cache_zip)
    shutil.make_archive(lib_cache_zip[:-4], 'zip', lib_cache_dir)
    # with zipfile.ZipFile(lib_cache_zip, "w") as zipref:
    #     for dirpath, dnames, fnames in os.walk(lib_cache_dir):
    #         for fname in fnames:
    #             if fname.endswith(".class"):
    #                 file = os.path.join(dirpath, fname)
    #                 zipref.write(file, arcname=file[len(lib_cache_dir) + 1:])
    return [lib_cache_zip]


def update_modified_classes(directories, cache_dir):
    cache_json = {}
    try:
        with open(os.path.join(cache_dir, "gradle_classes_cache.json")) as f:
            cache_json = json.load(f)
    except Exception as e:
        pass

    print("recalculating class file hashes...")
    modified_files = {}
    for directory in directories:
        directory_name = os.path.basename(directory)
        classes_dir = os.path.join(cache_dir, "classes", directory_name, "classes")
        if directory_name not in cache_json:
            cache_json[directory_name] = {}
        modified_timings = cache_json[directory_name]
        modified_files[directory_name] = {"class": [], "lib": []}
        modified_files_for_dir = modified_files[directory_name]["class"]        
        for dirpath, dnames, fnames in os.walk(classes_dir):
            for f in fnames:
                if f.endswith(".class"):
                    file = str(os.path.join(dirpath, f))
                    modified_time = int(1000 * os.path.getmtime(file))
                    hash_factory = hashlib.md5()
                    with open(file, "rb") as fp:
                        hash_factory.update(fp.read())
                    hash = str(hash_factory.digest())
                    if file not in modified_timings or modified_timings[file] != hash:
                        modified_files_for_dir.append(file)
                    modified_timings[file] = hash

        with open(os.path.join(directory, "manifest"), "r") as file:
            manifest = json.load(file)

        was_libs_modified = False
        library_files = []
        for library_dir in manifest["library-dirs"]:      
            for dirpath, dnames, fnames in os.walk(os.path.join(directory, library_dir)):
                for fname in fnames:
                    if fname.endswith(".jar"):
                        file = os.path.join(dirpath, fname)
                        library_files.append(file)
                        modified_time = int(1000 * os.path.getmtime(file))
                        key = "lib:" + file
                        if key not in modified_timings or modified_timings[key] != modified_time:
                            was_libs_modified = True
                        modified_timings[key] = modified_time
        if was_libs_modified:
            modified_files[directory_name]["lib"] += rebuild_library_cache(directory, library_files, cache_dir)
    return modified_files, cache_json


def save_modified_classes_cache(cache_json, cache_dir):
    with open(os.path.join(cache_dir, "gradle_classes_cache.json"), "w") as f:
        f.write(json.dumps(cache_json))


def run_d8(directory_name, modified_files, cache_dir, output_dex_dir):
    classpath_directory = make_config.get_path("toolchain/classpath")

    d8_libs = []
    for dirpath, dnames, fnames in os.walk(classpath_directory):
        for fname in fnames:
            if fname.endswith(".jar"):
                d8_libs += ["--lib", os.path.join(dirpath, fname)]

    dex_classes_dir = os.path.join(cache_dir, "d8", directory_name)
    classes_dir = os.path.join(cache_dir, "classes", directory_name, "classes")
    jar_dir = os.path.join(cache_dir, "classes", directory_name, "libs", directory_name + "-all.jar")
    ensure_directory(dex_classes_dir)
    
    modified_classes = modified_files["class"]
    modified_libs = modified_files["lib"]

    print("dexing libraries...")

    call_list = ["java", "-jar", make_config.get_path("toolchain/bin/lib/d8.jar")] + modified_libs + d8_libs + ["--min-api", "17", "--lib", jar_dir]
    for dirpath, dnames, fnames in os.walk(classpath_directory):
        for fname in fnames:
            if fname.endswith(".jar"):
                call_list += ["--classpath", os.path.join(dirpath, fname)]
    call_list += ["--intermediate", "--output", dex_classes_dir]
    result = subprocess.call(call_list)
    if result != 0:
        return result

    print("dexing classes...")
    index = 0
    max_span_size = 128
    while index < len(modified_classes):
        modified_classes_span = modified_classes[index:min(index + max_span_size, len(modified_classes))]
        call_list = ["java", "-jar", make_config.get_path("toolchain/bin/lib/d8.jar")] + modified_classes_span + d8_libs + ["--min-api", "17", "--lib", jar_dir]
        for dirpath, dnames, fnames in os.walk(classpath_directory):
            for fname in fnames:
                if fname.endswith(".jar"):
                    call_list += ["--classpath", os.path.join(dirpath, fname)]
        call_list += ["--intermediate", "--file-per-class", "--output", dex_classes_dir]
        result = subprocess.call(call_list)
        if result != 0:
            return result
        index += max_span_size
        print("dexing classes: ", min(index, len(modified_classes)), "/", len(modified_classes), " completed")

    print("compressing changed parts...")
    dex_zip_file = os.path.join(cache_dir, "d8", directory_name + ".zip")    
    with zipfile.ZipFile(dex_zip_file, 'w') as zip_ref:
         for dirpath, dnames, fnames in os.walk(dex_classes_dir):
                for fname in fnames:
                    if fname.endswith(".dex"):
                        file = os.path.join(dirpath, fname)
                        zip_ref.write(file, arcname=file[len(dex_classes_dir) + 1:])


    print("preparing output...")
    ensure_directory(output_dex_dir)
    for fname in os.listdir(output_dex_dir):
        if fname.endswith(".dex"):
            os.remove(fname)

    print("merging dex...")
    call_list = ["java", "-jar", make_config.get_path("toolchain/bin/lib/d8.jar"), dex_zip_file, "--min-api", "17", "--debug", "--intermediate", "--output", output_dex_dir]
    return subprocess.call(call_list)


def build_java_directories(directories, output_dir, cache_dir, classpath):
    ensure_directory(output_dir)
    ensure_directory(cache_dir)

    for directory in directories:
        dex_dir = os.path.join(output_dir, os.path.basename(directory))
        clear_directory(dex_dir)
        ensure_directory(dex_dir)
        copy_file(os.path.join(directory, "manifest"), os.path.join(dex_dir, "manifest"))

    setup_gradle_project(output_dir, cache_dir, directories, classpath)
    gradle_executable = make_config.get_path("toolchain/bin/gradlew.bat")
    result = subprocess.call([gradle_executable, "-p", cache_dir, "shadowJar"])
    if result != 0:
        print(f"java compilation failed with code {result}")
        return result

    modified_files, cache_json = update_modified_classes(directories, cache_dir)
    save_modified_classes_cache(cache_json, cache_dir)
    for directory_name, directory_modified_files in modified_files.items():
        print('\033[1m' + '\033[92m' + f"\nrunning dexer for {directory_name}\n" + '\033[0m')
        result = run_d8(directory_name, directory_modified_files, cache_dir, os.path.join(output_dir, directory_name))
        if result != 0:
            print(f"failed to dex {directory_name} with code {result}")
            return result

    save_modified_classes_cache(cache_json, cache_dir)
    print('\033[1m' + '\033[92m' + "\n****SUCCESS****\n" + '\033[0m')
    return result


def build_list(working_dir):
    dirs = os.listdir(working_dir)
    if "order.txt" in dirs:
        order = open(os.path.join(working_dir, "order.txt"), "r")
        dirs = order.read().splitlines()
    else:
        dirs = list(filter(lambda name: os.path.isdir(os.path.join(working_dir, name)), dirs))
    return dirs


def setup_gradle_project(output_dir, cache_dir, directories, classpath):
    file = open(os.path.join(cache_dir, "settings.gradle"), "w")
    file.writelines(["include ':%s'\nproject(':%s').projectDir = file('%s')\n" % (os.path.basename(item), os.path.basename(item), item.replace("\\", "\\\\")) for item in directories])
    file.close()

    for directory in directories:
        with open(os.path.join(directory, "manifest"), "r") as file:
            manifest = json.load(file)

        source_dirs = manifest["source-dirs"]
        library_dirs = manifest["library-dirs"]
        build_dir = os.path.join(cache_dir, "classes")
        dex_dir = os.path.join(output_dir, os.path.basename(directory))
        ensure_directory(build_dir)
        ensure_directory(dex_dir)

        if make_config.get_value("java.gradle.keepLibraries", True):
            for library_dir in library_dirs:
                src_dir = os.path.join(directory, library_dir)
                if os.path.isdir(src_dir):
                    copy_directory(src_dir, os.path.join(dex_dir, library_dir), clear_dst=True)

        if make_config.get_value("java.gradle.keepSources", False):
            for source_dir in source_dirs:
                src_dir = os.path.join(directory, source_dir)
                if os.path.isdir(src_dir):
                    copy_directory(src_dir, os.path.join(dex_dir, source_dir), clear_dst=True)

        with open(os.path.join(directory, "build.gradle"), "w", encoding="utf-8") as build_file:
            build_file.write("""
                plugins {
                    id 'com.github.johnrengelman.shadow' version '5.2.0'
                    id "java"
                }
        
                dependencies { 
                    """ + ("""compile fileTree('""" + "', '".join([path.replace("\\", "\\\\") for path in library_dirs]) + """') { include '*.jar' }""" if len(library_dirs) > 0 else "") + """
                }
        
                sourceSets {
                    main {
                        java {
                            srcDirs = ['""" + "', '".join([path.replace("\\", "\\\\") for path in source_dirs]) + """']
                            buildDir = \"""" + os.path.join(build_dir, "${project.name}").replace("\\", "\\\\") + """\"
                        }
                        resources {
                            srcDirs = []
                        }
                        compileClasspath += files('""" + "', '".join([path.replace("\\", "\\\\") for path in classpath]) + """')
                    }
                }
        
                tasks.register("dex") {
                    javaexec { 
                        main = "-jar";
                        args = [
                            \"""" + make_config.get_path("toolchain/bin/dx.jar").replace("\\", "\\\\") + """\",
                            "--dex",
                            "--multi-dex",
                            "--output=\\\"""" + os.path.join(dex_dir, ".").replace("\\", "\\\\") + """\\\"",
                            \"""" + os.path.join(build_dir, "${project.name}", "libs", "${project.name}-all.jar").replace("\\", "\\\\") + """\"
                        ]
                    } 
                }
            """)


def cleanup_gradle_scripts(directories):
    for path in directories:
        gradle_script = os.path.join(path, "build.gradle")
        if os.path.isfile(gradle_script):
            os.remove(gradle_script)


def compile_all_using_make_config():
    import time
    start_time = time.time()

    overall_result = 0
    output_dir = make_config.get_path("output/java")
    cache_dir = make_config.get_path("toolchain/build/gradle")
    ensure_directory(output_dir)
    ensure_directory(cache_dir)

    directories = []
    directory_names = []
    for directory in make_config.get_filtered_list("compile", prop="type", values=("java",)):
        if "source" not in directory:
            print("skipped invalid java directory json", directory, file=sys.stderr)
            overall_result = -1
            continue
        for path in make_config.get_paths(directory["source"]):
            if not os.path.isdir(path):
                print("skipped non-existing java directory path", directory["source"], file=sys.stderr)
                overall_result = -1
                continue
            name = os.path.basename(path)
            if name in directory_names:
                print("skipped java directory with duplicate name", name, file=sys.stderr)
                overall_result = -2
                continue
            directory_names.append(name)
            directories.append(path)

    if overall_result != 0:
        print("failed to get java directories", file=sys.stderr)
        return overall_result
    else:
        with open(os.path.join(output_dir, "order.txt"), "w") as f:
            f.write("\n".join(directory_names))

    if len(directories) > 0:
        classpath_directories = [make_config.get_path("toolchain/classpath")] + make_config.get_value("java.gradle.classpath", [])
        overall_result = build_java_directories(directories, output_dir, cache_dir, get_classpath_from_directories(classpath_directories))
        if overall_result != 0:
            print(f"failed, clearing compiled directories {directories} ...")
            for directory_name in directory_names:
                clear_directory(make_config.get_path("output/" + directory_name))
    cleanup_gradle_scripts(directories)

    print(f"completed java build in {int((time.time() - start_time) * 100) / 100}s with result {overall_result} - {'OK' if overall_result == 0 else 'ERROR'}")
    return overall_result


def clear_gradle_cache_directory():
    shutil.rmtree(make_config.get_path("toolchain/build/gradle"))
    return 0


if __name__ == '__main__':
    compile_all_using_make_config()