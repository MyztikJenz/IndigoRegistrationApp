import csv
import argparse
import hashlib

argparser = argparse.ArgumentParser(description="")
argparser.add_argument("-i", "--input", dest="input", action="store", required=True, help="")

programArgs = argparser.parse_args()
input = programArgs.input

with open(input) as csvfile:
    r = csv.DictReader(csvfile)
    for row in r:
        # print(row["name"], row["class"])
        key = row["name"] + "|" + row["class"] + "|" + row["grade"]
        md5hash = hashlib.md5(key.encode()).hexdigest()
        first7 = md5hash[:7]
        # print(f"{key} == {md5hash} [{first7}]")
        print(first7)
