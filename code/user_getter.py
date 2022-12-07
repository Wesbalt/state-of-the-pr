import common, sys, datetime, pprint, typing, concurrent.futures

if len(sys.argv) != 4:
	print("Usage: py %s <input> <tokens> <output>" % sys.argv[0])
	sys.exit(1)

input_path  = sys.argv[1]
tokens_path = sys.argv[2]
output_path = sys.argv[3]
common.tokens : [str] = common.read_lines_of_commented_file(tokens_path)
pr_html_urls  : [str] = common.read_lines_of_commented_file(input_path)
print(f"Read {len(common.tokens)} tokens and {len(pr_html_urls)} PRs")

repos = set()
for pr_html_url in pr_html_urls:
    # Example URL: https://github.com/netdata/netdata/pull/7645
    groups = pr_html_url.split("/")
    repo   = groups[3] + "/" + groups[4]
    repos.add(repo)

print(f"Got {len(repos)} repos")

prs : [(str, int)] = []
users : [(str, str, str, str)] = []
checked_usernames = set()
users_per_repo = 10

print(str(len(repos) * users_per_repo) + " users are to be found")

# Add the user to the list if it's a non-bot and has an associated email.
# Return True if the user was added, False if not.
def maybe_add_user(username : str, repo : str) -> bool:
    global users, checked_usernames

    if username in checked_usernames:  return False # Reject already checked users
    else:                              checked_usernames.add(username)

    # Docs: https://docs.github.com/en/rest/reference/users#get-a-user
    url = "https://api.github.com/users/" + username
    json : dict = common.request_github_data(url, False)

    if json["type"].lower() != "user" or "bot" in username:  return False # Reject bots

    email = json["email"]
    if not email:  return False # Reject users without an associated email

    # Accept the user
    name = json["name"] if json["name"] else ""
    name = name.replace(",", "") # Remove commas because the output is comma-separated data
    users.append((username, name, email, repo))
    print("\tAdded " + username)

    return True

def get_users_in_pr(pr_search_jsons : [dict], repo : str):
    users_added_this_repo = 0

    for pr_search_json in pr_search_jsons:

        # Maybe add the creator
        if maybe_add_user(pr_search_json["user"]["login"], repo):  users_added_this_repo += 1

        if users_added_this_repo >= users_per_repo:  return

        # Docs: https://docs.github.com/en/rest/reference/issues#list-timeline-events-for-an-issue
        pr_timeline_api_url     = f"https://api.github.com/repos/{repo}/issues/{pr_search_json['number']}/timeline"
        pr_timeline_jsons : [dict] = common.request_github_data(pr_timeline_api_url, True)

        for pr_timeline_json in pr_timeline_jsons:

            # Only these events count for selection
            # Docs: https://docs.github.com/en/developers/webhooks-and-events/events/issue-event-types
            events = ["closed", "merged", "reviewed", "commented"]

            if pr_timeline_json["event"].lower() in events:
                actor, _ = common.get_actor_of_timeline_event(pr_timeline_json)
                if not actor:  continue # Skip deleted users (their usernames are empty strings)
                # Maybe add the event's actor
                if maybe_add_user(actor, repo):  users_added_this_repo += 1

            if users_added_this_repo >= users_per_repo:  return

    if users_added_this_repo != users_per_repo:
        print(f"Internal error: did not find the desired amount of users in {repo} (wanted {users_per_repo}, got {users_added_this_repo})")
        sys.exit(1)

    print(f"\tFound {users_added_this_repo} users")

for i, repo in enumerate(repos):

    print("https://github.com/" + repo + ":")

    # Create the API URL
    # Docs: https://docs.github.com/en/search-github/searching-on-github/searching-issues-and-pull-requests
    pr_search_url  = "https://api.github.com/search/issues"
    pr_search_url += "?q=is:pr sort:created-desc repo:" + repo
    pr_search_url += "&per_page=100&page="

    # Queue the API calls
    executor = concurrent.futures.ThreadPoolExecutor()
    futures : [concurrent.futures.Future] = []
    pages = 10 # Request 10 pages because GitHub stores up to 1000 search results and we'll reach this limit exactly (100 items per page * 10 pages = 1000 items)
    for page_number in range(1, pages+1):
        future = executor.submit(common.request_github_data, pr_search_url + str(page_number), False)
        futures.append(future)

    # Execute the API calls in parallel
    pr_jsons : [dict] = []
    for future in futures:
        json = future.result()
        pr_jsons.extend(json["items"])
    executor.shutdown()

    print(f"\tFound {len(pr_jsons)} PRs")
    get_users_in_pr(pr_jsons, repo)
    print(f"Progress: {(i+1) / len(repos) :.1%}")

f = open(output_path, "w", encoding="utf-8")
for user in users:  f.write(",".join(user) + "\n")
f.close()

print("Wrote " + str(len(users)) + " users to " + output_path)

print("Done.")
