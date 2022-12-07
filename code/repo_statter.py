import sys, common, pprint, requests, statistics, datetime

if len(sys.argv) != 3:
	print("Usage: py %s <input> <tokens-file>" % sys.argv[0])
	sys.exit(1)

input_file_path  = sys.argv[1]
tokens_file_path = sys.argv[2]
common.tokens  : [str] = common.read_file(tokens_file_path, True)
pull_html_urls : [str] = common.read_file(input_file_path,  True)
print(f"Read {len(common.tokens)} tokens and {len(pull_html_urls)} pulls")

repos = set()
for pull_html_url in pull_html_urls:
    # Sample URL: https://github.com/netdata/netdata/pull/7645
    groups = pull_html_url.split("/")
    repo   = groups[3] + "/" + groups[4]
    repos.add(repo)

print(f"Found {len(repos)} repos")

all_age_values          = []
all_closed_pulls_values = []
all_commits_values      = []
all_contributors_values = []
all_forks_values        = []
all_size_values         = []
all_stars_values        = []

for i, repo in enumerate(repos):

    # Do the API call
    # Docs: https://docs.github.com/en/rest/reference/repos#get-a-repository
    get_repo_api_url = "https://api.github.com/repos/" + repo
    get_repo_json    = common.request_github_data(get_repo_api_url, False)

    # Get the readily available data from the API response
    forks = int(get_repo_json["forks"])
    size  = int(get_repo_json["size"]) / 1000 # Expressed in megabytes
    stars = int(get_repo_json["stargazers_count"])

    # Get repo age
    start = common.string_to_datetime(get_repo_json["created_at"])
    end   = datetime.datetime.now()
    age   = (end.year - start.year) + (end.month - start.month)/12 # Expressed in years

    # Get the number of closed pulls, commits and contributors by inspecting HTML code
    closed_pulls = common.get_closed_pull_count(repo)
    commits      = common.get_commit_count(repo)
    contributors = common.get_contributor_count(repo)

    all_age_values         .append(age)
    all_closed_pulls_values.append(closed_pulls)
    all_commits_values     .append(commits)
    all_contributors_values.append(contributors)
    all_forks_values       .append(forks)
    all_size_values        .append(size)
    all_stars_values       .append(stars)

    # Useful prints
    '''print(f"https://github.com/{repo}")
    print(f"\tAge: {age}")
    print(f"\tClosed pulls: {closed_pulls}")
    print(f"\tCommits: {commits}")
    print(f"\tContributors: {contributors}")
    print(f"\tForks: {forks}")
    print(f"\tSize (MB): {size}")
    print(f"\tStars: {stars}")'''

    print(f"Progress: {(i+1) / len(repos) :.1%}")

def get_stats(l : [float]) -> (int,int,int,int):
    return (
        round(min(l)),
        round(statistics.median(l)),
        round(max(l)),
        statistics.mean(l),
    )

age_stats          = get_stats(all_age_values)
closed_pulls_stats = get_stats(all_closed_pulls_values)
commits_stats      = get_stats(all_commits_values)
contributors_stats = get_stats(all_contributors_values)
forks_stats        = get_stats(all_forks_values)
size_stats         = get_stats(all_size_values)
stars_stats        = get_stats(all_stars_values)

print()
print("Attribute | Min | Median | Max | Mean")
print("-------------------------------------")
print(f"Age (years)  | {age_stats[0]} | {age_stats[1]} | {age_stats[2]} | {age_stats[3]}")
print(f"Closed pulls | {closed_pulls_stats[0]} | {closed_pulls_stats[1]} | {closed_pulls_stats[2]} | {closed_pulls_stats[3]}")
print(f"Commits      | {commits_stats[0]} | {commits_stats[1]} | {commits_stats[2]} | {commits_stats[3]}")
print(f"Contributors | {contributors_stats[0]} | {contributors_stats[1]} | {contributors_stats[2]} | {contributors_stats[3]}")
print(f"Forks        | {forks_stats[0]} | {forks_stats[1]} | {forks_stats[2]} | {forks_stats[3]}")
print(f"Size (MB)    | {size_stats[0]} | {size_stats[1]} | {size_stats[2]} | {size_stats[3]}")
print(f"Stars        | {stars_stats[0]} | {stars_stats[1]} | {stars_stats[2]} | {stars_stats[3]}")
print()

print("Done.")
