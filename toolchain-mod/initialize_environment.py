'''
YOU HAVE TO RUN THIS SCRIPT WHEN YOU HAVE JUST
INITIALIZED THE PROJECT OR CLONED YOUR PROJECT'S
GITHUB REPOSITORY. WITHOUT RUNNING IT, NONE OF
THE BUILD TASKS WILL WORK
'''

from urllib.request import urlretrieve
from zipfile import ZipFile
from os import remove, getcwd
from os.path import join
from subprocess import call

print("Initializing development environment...")
url = "https://codeload.github.com/DMHYT/innercore-mod-toolchain/zip/gitignored-toolchain"
archive_path = join(getcwd(), "toolchain", "archive.zip")
urlretrieve(url=url, filename=archive_path)
with ZipFile(archive_path, 'r') as archive:
    archive.extractall(join(getcwd(), "toolchain"))
remove(archive_path)
call(["python", join(getcwd(), "toolchain", "python", "task.py"), "loadDocs loadJavaDependencies loadAdbAndBin downloadICHeaders downloadGnustlHeaders downloadNdkIfNeeded"])
print("complete!")