import sys, os, common, datetime, pprint, concurrent.futures

# TODO Remove support for multiple languages
# TODO Make sure no duplicates are selected

if len(sys.argv) != 3:
	print("Usage: py %s <tokens> <output>" % sys.argv[0])
	sys.exit(1)

tokens_file_path = sys.argv[1]
output_file_name = sys.argv[2]
common.tokens : [str] = common.read_lines_of_file(tokens_file_path, True)
print(f"Read {len(common.tokens)} tokens")

languages = ["PHP"]
# languages = ["C", "CSharp", "CPP", "Go", "Java", "JavaScript", "PHP", "Python", "Ruby", "TypeScript"]
pulls_per_language = 10000
max_pulls_per_repo = 1000 # Max 1000
minimum_contributor_count = 50
minimum_closed_pull_count = 200

print(f"{len(languages) * pulls_per_language} pulls are to be selected")

current_date : datetime.datetime = datetime.date.today()
one_year_before_today_date    : datetime.datetime = datetime.datetime(current_date.year - 1, current_date.month, current_date.day)
three_years_before_today_date : datetime.datetime = datetime.datetime(current_date.year - 3, current_date.month, current_date.day)
repo_creation_date : str = one_year_before_today_date   .strftime("%Y-%m-%d")
pull_creation_date : str = three_years_before_today_date.strftime("%Y-%m-%d")

executor = concurrent.futures.ThreadPoolExecutor()
futures : [concurrent.futures.Future] = []

repos_per_language : [(str, [str])] = []

for language in languages:
    api_url = "https://api.github.com/search/repositories"
    query = f"created:<={repo_creation_date} fork:false language:{language} sort:updated-desc"
    future : concurrent.futures.Future = executor.submit(common.search_github, api_url, query, 1000)
    futures.append(future)

print("Searching for repos...")

for language, future in zip(languages, futures):
    repos_json : dict = future.result()
    repos = [json["full_name"] for json in repos_json]
    repos_per_language.append((language, repos))
    print(f"Found {len(repos)} repos written in {language}")

executor.shutdown()
repo_count = sum([len(repos) for _, repos in repos_per_language])
print(f"{repo_count} repos found in total")

all_pulls : [str] = []

def does_pr_qualify(repo_name : str, pr_json : [dict]) -> bool:

    # Disqualify PRs by bots
    if not common.user_is_human(pr_json["user"]):  return False

    # Docs: https://docs.github.com/en/rest/reference/pulls#list-commits-on-a-pull-request
    commits_api_url_template = "https://api.github.com/repos/%s/pulls/%d/commits"
    commits_api_url = commits_api_url_template % (repo_name, pr_json["number"])
    commit_jsons    = common.request_github_data(commits_api_url, True)

    # Find out if the PR has any status checks. Execute the API calls
    # in parallel because one call is necessary for each commit.
    # Docs: https://docs.github.com/en/rest/commits/statuses#get-the-combined-status-for-a-specific-reference
    commit_status_api_url_template = "https://api.github.com/repos/" + repo_name + "/commits/{sha}/status"
    executor = concurrent.futures.ThreadPoolExecutor()
    commit_status_futures : [concurrent.futures.Future] = []

    for commit_json in commit_jsons:
        sha = commit_json["sha"]
        commit_status_url = commit_status_api_url_template.replace("{sha}", sha)
        commit_status_futures.append(executor.submit(common.request_github_data, commit_status_url, False))

    commit_status_jsons : [dict] = [future.result() for future in commit_status_futures]
    executor.shutdown()

    for commit_status_json in commit_status_jsons:
        if commit_status_json["state"].lower() != "pending":
            # A non-pending status state means failure/success
            # occurred, implying the commit has been checked
            return True

    return False

def fetch_qualified_pulls(repo : str):
    global pulls_selected_in_this_language

    api_url_template = "https://api.github.com/search/issues"
    query = f"type:pr state:closed repo:{repo} created:>={pull_creation_date} sort:created-desc"
    pulls_json = common.search_github(api_url_template, query, max_pulls_per_repo)

    pulls : [str] = []
    consecutive_disqualified_pulls = 0

    for pull_json in pulls_json:

        if does_pr_qualify(repo, pull_json):

            all_pulls.append(pull_json["html_url"])
            progress = len(all_pulls) / (pulls_per_language * len(languages)) * 100
            print(f"Selected {pull_json['html_url']} ({progress:.3f}%)")
            pulls_selected_in_this_language += 1
            consecutive_disqualified_pulls = 0

        else:

            consecutive_disqualified_pulls += 1
            # Give up on this page if too many consecutive PRs fail to qualify, to save time and API calls
            if consecutive_disqualified_pulls >= 5:
                # print(f"Skipping {repo} (too many consecutive disqualified pulls)")
                break

        if pulls_selected_in_this_language >= pulls_per_language:  break

pulls_selected_in_this_language = 0

print("Examining repos...")

for language, repos in repos_per_language:

    pulls_selected_in_this_language = 0

    for repo in repos:
        if common.get_contributor_count(repo) < minimum_contributor_count:
            # print(f"Skipping {repo} (too few contributors)")
            continue
        if common.get_closed_pull_count(repo) < minimum_closed_pull_count:
            # print(f"Skipping {repo} (too few closed pulls)")
            continue
        # print(f"Fetching pulls from {repo}...")
        fetch_qualified_pulls(repo)
        if pulls_selected_in_this_language >= pulls_per_language:  break

    if pulls_selected_in_this_language < pulls_per_language:
        print(f"Warning: found too few {language} pulls (wanted {pulls_per_language}, got {pulls_selected_in_this_language})")

f = open(output_file_name, "w")
for pull in all_pulls:  f.write(pull + "\n")
f.close()

print(f"Wrote {len(all_pulls)} lines to \"{output_file_name}\"")
print("Done.")
