import sys, os, common, pprint, statistics

if len(sys.argv) != 2:
	print("Usage: py %s <extraction_directory>" % sys.argv[0])
	sys.exit(1)

path_to_extraction_files = sys.argv[1]
extraction_filenames = os.listdir(path_to_extraction_files)
print(f"Found {len(extraction_filenames)} extraction files")

# A dictionary that connects each factor name to its values in all states.
# Example entry: "added_lines" : [2, 10, 30, -1, 3.14]
factor_dict = {}

# Find outliers in the filtration file
outlier_filenames : [str] = []

print("Reading extraction files... (Takes a while if cold)")

# TODO Remove me
# files = []
# factor_of_interest = "test_files"

ccc = 0 # TODO Remove me

# Read the extraction files while skipping outliers
extraction_files_read = 0
for extraction_filename in extraction_filenames:

    if extraction_filename in outlier_filenames:  continue
    extraction_files_read += 1

    filepath = os.path.join(path_to_extraction_files, extraction_filename)
    metadata, readiness_factors, middle_factors, closure_factors = common.read_extraction_file(filepath)

    for i in range(len(readiness_factors)):
        # Add the factor name and values to the dictionary. The
        # factor names and values are ordered consistently such
        # that index i refers to the same factor.

        factor_name = readiness_factors[i][0]
        if factor_name not in factor_dict:  factor_dict[factor_name] = []

        # TODO Remove me
        factors = [readiness_factors[i][1]]
        # factors = [readiness_factors[i][1], middle_factors[i][1], closure_factors[i][1]]

        factor_dict[factor_name] += factors

        # TODO Remove me
        if factors[0] == 0:
            ccc += 1

        # TODO Remove me
        # if readiness_factors[i][0] == factor_of_interest:
        #     files.append((metadata["html_url"], readiness_factors[i][1], extraction_filename,  "ready"))
        # if middle_factors[i][0] == factor_of_interest:
        #     files.append((metadata["html_url"],    middle_factors[i][1], extraction_filename,  "middle"))
        # if closure_factors[i][0] == factor_of_interest:
        #     files.append((metadata["html_url"],   closure_factors[i][1], extraction_filename, "closure"))

print(f"{extraction_files_read} extraction files read")

# TODO Remove me
# files = sorted(files, key=lambda x: x[1], reverse=True)
# print(factor_of_interest)
# for f in files[:20]:
#     url, value, fname, state = f
#     print(f"  {url}")
#     print(f"    filename = {fname}")
#     print(f"    value = {value} ({state} state)")
#     print()
# sys.exit()

print()
print("Factor | Min | 25% | Median | 75% | Max | Mean | Stdev")
print("------------------------------------------------------")

for name in sorted(factor_dict):
    values      = factor_dict[name]
    quantiles   = statistics.quantiles(values, n=4)
    quantile_25 = round(quantiles[0], 1)
    quantile_50 = round(quantiles[1], 1)
    quantile_75 = round(quantiles[2], 1)
    mean        = round(statistics.mean(values), 1)
    stdev       = statistics.stdev(values)
    print(f"{name} | {min(values)} | {quantile_25} | {quantile_50} | {quantile_75} | {max(values)} | {mean} | {stdev}")

print()
print("Done.")

print(ccc) # TODO Remove me
