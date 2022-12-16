import sys, common, pprint, concurrent, datetime, random, os, copy, concurrent.futures, json, csv

# TODO Rename factors source code
# TODO Mark the custom timeline

if len(sys.argv) != 4:
	print("Usage: py %s <tokens_file> <selection_file> <extraction_csv>" % sys.argv[0])
	sys.exit(1)

tokens_file_path     = sys.argv[1]
selection_file_path  = sys.argv[2]
extraction_file_path = sys.argv[3]

# Read the GitHub API tokens
common.tokens : [str] = common.read_file(tokens_file_path, True)
print(f"Read {len(common.tokens)} tokens")

# Read the selected PRs
f = open(selection_file_path, "r", newline="")
selected_pr_urls : [str] = f.read().splitlines()
f.close()
print(f"Read {len(selected_pr_urls)} selected PRs")

# Read the extracted PRs
extracted_pr_dicts : [dict] = []
if os.path.exists(extraction_file_path):
    extracted_pr_dicts = common.read_csv_as_dicts(extraction_file_path)
    print(f"Read {len(extracted_pr_dicts)} extracted PRs")
else:
    print("Did not find an existing extraction file")

'''
csv_file = open(, "r", newline="")
csv_reader = csv.reader(csv_file)
next(csv_reader) # Skip the column header
extracted_pr_urls : [str] = [row[0] for row in csv_reader]
csv_file.close()
'''

# Calculate the PRs that need to be extracted
extracted_pr_urls  : [str] = [pr_dict["URL"] for pr_dict in extracted_pr_dicts]
pr_urls_to_extract : [str] = list(set(selected_pr_urls) - set(extracted_pr_urls))
print(f"{len(pr_urls_to_extract)} PRs are to be extracted")
pr_urls_to_extract = sorted(pr_urls_to_extract) # Sort them for the sake of determinism

'''
# Set this to non-zero if you would like to extract a sample
sample_size = 0
if sample_size:
    pr_html_urls = random.sample(pr_html_urls, sample_size)
    print(f"Sample of size {sample_size} taken")
'''

'''
Return the timestamp string of a GitHub event. The following events are supported:
Timeline events: https://docs.github.com/en/rest/reference/issues#list-timeline-events-for-an-issue
Review comments: https://docs.github.com/en/rest/pulls/comments#list-review-comments-on-a-pull-request
'''
def get_event_timestamp(event_json : dict) -> str:
    if "created_at" in event_json:  return event_json["created_at"]

    if   event_json["event"] == "committed":  return event_json["committer"]["date"]
    elif event_json["event"] == "reviewed":   return event_json["submitted_at"]

    print("Internal error: could not find timestamp")
    pprint.pprint(event_json)
    sys.exit(1)

'''
Create a PR timeline based on its GitHub timeline and review comments.
Timeline docs: https://docs.github.com/en/rest/reference/issues#list-timeline-events-for-an-issue
Review comments docs: https://docs.github.com/en/rest/pulls/comments#list-review-comments-on-a-pull-request
'''
def create_pr_timeline(github_timeline : [dict], review_comments : [dict], get_commit_jsons : [dict]) -> [dict]:

    custom_timeline : [dict] = []

    # Expand groups commit comments into individual events.
    # Also supplement JSON data for debugging purposes.
    for github_timeline_index, github_event in enumerate(github_timeline):
        custom_events = []

        if github_event["event"].lower() == "commit-commented":
            # Commit comments are grouped, make them into distinct events
            for commit_comment in github_event["comments"]:
                commit_comment["event"] = "commit-commented"
                custom_events.append(commit_comment)
        else:
            # All other events are single events, add them without modification
            custom_events.append(github_event)

        # Supplement data
        for custom_event in custom_events:
            custom_event["origin"]      = "timeline"
            custom_event["array_index"] = github_timeline_index

        custom_timeline.extend(custom_events)

    # Supplement "committed" events with complete actor login data
    for event in custom_timeline:

        if event["event"].lower() == "committed":
            found_sha = False

            for commit_json in get_commit_jsons:
                if commit_json["sha"] == event["sha"]:
                    found_sha  = True
                    actor_name = ""
                    actor_type = ""

                    if commit_json["author"]:
                        actor_name = commit_json["author"]["login"]
                        actor_type = commit_json["author"]["type"]
                    else:
                        # AFAIK, this means the commit cannot be linked to a GitHub account.
                        # Just use the display name and assume the committer is human.
                        actor_name = event["author"]["name"]
                        actor_type = "User"

                    event["committer"]["login"] = actor_name
                    event["committer"]["type"]  = actor_type

            if not found_sha:
                print("Internal error: did not find matching SHA while supplementing login data in a \"committed\" event")
                sys.exit(1)

    # Restore the original states of dismissed review events. Otherwise
    # we cannot inspect the current state in a specific point in time.
    for event in custom_timeline:

        if event["event"].lower() != "review_dismissed":  continue

        dismissed_event_id = event["dismissed_review"]["review_id"]
        original_state_of_dismissed_event = event["dismissed_review"]["state"].lower()

        # Find the dismissed review and restore its original state.
        # Finding the dismissed review is not a guarantee as some
        # are simply missing from the timeline.
        # Example: https://api.github.com/repos/netdata/netdata/issues/7132
        # Note that review 304275957 is dismissed on index 19 in
        # the timeline, but there is no such review.
        for e in custom_timeline:
            if e["event"].lower() != "reviewed":  continue

            if e["id"] == dismissed_event_id:
                e["state"] = original_state_of_dismissed_event
                break

    # Add the review comments to the custom timeline
    for review_comments_index, comment in enumerate(review_comments):
        comment["event"]       = "review_commented"
        comment["origin"]      = "review_comments"
        comment["array_index"] = review_comments_index
        custom_timeline.append(comment)

    # Remove duplicate review comments
    def keep_event(event_a : dict) -> bool:
        if event_a["event"] == "review_commented":
            for event_b in custom_timeline:
                if event_b["event"] == "reviewed" and event_a["pull_request_review_id"] == event_b["id"]:
                    # Duplicate review comments detected
                    return False
        return True
    custom_timeline = list(filter(keep_event, custom_timeline))

    # Supplement the JSON data
    for event in custom_timeline:
        actor, is_user         = common.get_event_actor(event)
        event["actor"]         = actor
        event["actor_is_user"] = is_user # TODO Rename field to actor_is_human
        event["timestamp"]     = get_event_timestamp(event)

    # Sort events chronologically
    custom_timeline.sort(key = lambda event: common.string_to_datetime(event["timestamp"]))

    # Remove events that happened after closure. If the PR
    # was reopened and closed again, use the final close.
    index_of_final_close = -1
    for i, event in enumerate(custom_timeline):
        if event["event"].lower() == "closed":
            index_of_final_close = i

    if index_of_final_close == -1:
        # In extremely rare cases, a timeline may lack the "closed" event.
        # Example: https://api.github.com/repos/pygame/pygame/issues/3124/timeline
        # In this case, set the index to the last event.
        index_of_final_close = len(custom_timeline)-1
        print("Warning: could not find closed event, set index to last event")

    custom_timeline = custom_timeline[:index_of_final_close + 1]

    return custom_timeline

def event_is_participatory(event : dict) -> bool:
    
    # These are the GitHub timeline events which do not count towards participation.
    # Both "automatic_base_change_failed" and "automatic_base_change_succeeded" concern
    # an automatic process performed by GitHub.
    # Also, @-mentions create subsequent "mentioned" and "subscribed" events for which
    # the actor is the mentioned user despite not taking any action.
    non_participatory_events = ["automatic_base_change_failed", "automatic_base_change_succeeded", "mentioned", "subscribed"]

    return event["actor_is_user"] and event["event"].lower() not in non_participatory_events

# The timeline can contain any of GitHub's timeline events:
# https://docs.github.com/en/developers/webhooks-and-events/events/issue-event-types
# As well as a "review_commented" event:
# https://docs.github.com/en/rest/pulls/comments#list-review-comments-on-a-pull-request
# As well as several events not covered by GitHub's documentation.
def generate_state(timeline : [dict], get_pr_json : dict, commit_status_jsons : [dict], get_commit_jsons : [dict]) -> (dict, str):

    factors = {
        "Approvals"         : 0, # No. of reviews in the approved state
        "Assignees"         : 0, # No. of assignees
        "Build_Fail_Rate"   : 0, # Proportion of failed builds
        "Change_Requests"   : 0, # No. of reviews in the changes requested state
        "Changed_Files"     : 0, # No. of files changed
        "Conflicts"         : 0, # No. of occurrences of the word "conflict" in the PR thread
        "Cross_References"  : 0, # No. of cross-references to this PR from another PR or issue
        "Discussion"        : 0, # No. of discussion comments
        "Events"            : 0, # No. of events on this PR
        "Fixes"             : 0, # No. of references to other issues and PRs in the PR thread
        "Intermission"      : 0, # Average time between events, in minutes
        "Labels"            : 0, # No. of labels
        "Last_Build_Status" : 1, # 0 if the last commit had any failing status checks, 1 otherwise
        "Mentions"          : 0, # No. of @-mentions in the PR
        "Milestones"        : 0, # No. of milestones this PR contributes to
        "Participants"      : 0, # No. of unique non-bot users who have created participatory events in the PR thread
        "PR_Commits"        : 0, # No. of commits
        "Review_Comments"   : 0, # No. of review comments, including subsequent comments on reviews
        "Test_Files"        : 0, # No. of test files
    }

    current_title = get_pr_json["title"] # Assume the latest title as the current one. It changes on "renamed" events

    participants = set()
    participants.add(get_pr_json["user"]["login"]) # Add the creator

    commit_messages     : [str] = []
    discussion_comments : [str] = []
    review_comments     : [str] = []
    commit_comments     : [str] = []

    total_builds  = 0
    failed_builds = 0
    filenames     = set() # Unique filenames touched by the commits # TODO Rename

    for i, event in enumerate(timeline):

        event_type = event["event"]

        if event["actor"] not in participants and event_is_participatory(event):
            participants.add(event["actor"])
            factors["Participants"] += 1

        if event_type == "assigned":
            factors["Assignees"] += 1

        elif event_type == "unassigned":
            factors["Assignees"] -= 1
            # Don't let this factor go negative. This happens due to duplicate unassignments.
            # Example: https://api.github.com/repos/angular/angular/issues/34305/timeline?per_page=100
            # See index 57 and 58 where the same user is unassigned by the same actor at the same time.
            if factors["Assignees"] < 0:  factors["Assignees"] = 0

        elif event_type == "commented":
            factors["Discussion"] += 1
            discussion_comments.append(event["body"])

        elif event_type == "comment_deleted":
            # There is no official doc on this and removed comments are
            # deleted from the timeline anyway, making it impossible to
            # know the number of comments using the API.
            # Example:
            # Pull:      https://github.com/angular/angular/pull/33959
            # Timeline:  https://api.github.com/repos/angular/angular/issues/33959/timeline
            # (Notice how mary-poppins has commented thrice but the
            # timeline data claims only two comments.)
            # Considering this and the rarity of this event (used 8
            # times in a sample of 1,000 PRs), let's just ignore it.
            pass

        elif event_type == "committed":

            message = event["message"]
            commit_messages.append(message)

            # Get the build status
            found_sha = False
            for status_json in commit_status_jsons:

                if status_json["sha"] == event["sha"]:
                    found_sha = True

                    status_state = status_json["state"].lower()
                    factors["Last_Build_Status"] = int(status_state != "failure")
                    total_builds += 1
                    if status_state == "failure":  failed_builds += 1

                    break # We found the matching SHA, let's exit

            if not found_sha:
                return None, "could not find commit status of commit " + event["sha"]

            # Some commits do not reflect any work by the author, e.g., rebasing.
            # Example: https://github.com/yugabyte/yugabyte-db/pull/12846/commits
            # These tend to have similar commit messages, and the following
            # heuristic exploits that to discount such commits in some factors.
            lines = message.splitlines()
            if lines:
                first_line = lines[0].lower()
                if "merge" in first_line:
                    if "branch"       in first_line or \
                       "master"       in first_line or \
                       "commit"       in first_line or \
                       "pull request" in first_line:
                        continue # Skip this commit

            factors["PR_Commits"] += 1

            # Get the source and test files touched by the PR
            found_sha = False
            for commit_json in get_commit_jsons:

                if commit_json["sha"] == event["sha"]:
                    found_sha = True

                    for file in commit_json["files"]:
                        fname = file["filename"]
                        if fname not in filenames:
                            # This commit touched a new path!
                            filenames.add(fname)
                            factors["Changed_Files"] += 1
                            if "test" in fname:  factors["Test_Files"] += 1

                    break # We found the matching SHA, let's exit

            if not found_sha:
                return None, "could not find files touched by commit " + event["sha"]

        elif event_type == "commit-commented":
            # Keep in mind the create_pr_timeline function has modified
            # these events so they differ from GitHub's convention.
            # Use pprint.pprint(event) for details.
            commit_comments.append(event["body"])

        elif event_type == "cross-referenced":
            factors["Cross_References"] += 1

        elif event_type == "milestoned":
            factors["Milestones"] += 1

        elif event_type == "demilestoned":
            factors["Milestones"] -= 1

        elif event_type == "labeled":
            factors["Labels"] += 1

        elif event_type == "unlabeled":
            factors["Labels"] -= 1
            # Don't let this factor go negative. This happens due to duplicate unlabeling.
            # Example: https://api.github.com/repos/palantir/atlasdb/issues/6005/timeline
            # See index 3-7 where the "merge when ready" label is applied and then unlabeled four times.
            if factors["Labels"] < 0:  factors["Labels"] = 0

        elif event_type == "mentioned":
            factors["Mentions"] += 1

        elif event_type == "renamed":
            current_title = event["rename"]["to"]

        elif event_type == "review_commented":
            # This event originates from GitHub's review comments data,
            # unlike all other events that come from GitHub's timeline.
            # Docs: https://docs.github.com/en/rest/pulls/comments#list-review-comments-on-a-pull-request
            # Example: https://api.github.com/repos/pingcap/tidb/pulls/14123/comments
            factors["Review_Comments"] += 1
            review_comments.append(event["body"])

        elif event_type == "reviewed":
            factors["Review_Comments"] += 1
            if event["body"]:  review_comments.append(event["body"])

            review_state = event["state"].lower()

            if review_state == "dismissed":
                return None, f"unexpected dismissed review state in timeline (index {event['array_index']})"
            elif review_state == "approved":
                factors["Approvals"] += 1
            elif review_state == "changes_requested":
                factors["Change_Requests"] += 1
            elif review_state == "commented":
                pass
            else:
                return None, f"unknown review state in timeline (index {event['array_index']})"

        elif event_type == "review_dismissed":
            # This is the original review state rather than the current one,
            # because the original state was restored in create_pr_timeline
            state = event["dismissed_review"]["state"].lower()

            if state == "approved":
                factors["Approvals"] -= 1
            elif state == "changes_requested":
                factors["Change_Requests"] -= 1

            # Don't let these factors go negative. This appears to happen
            # due to reviews not on the timeline being dismissed.
            # Example 1 (see index 11): https://api.github.com/repos/certbot/certbot/issues/7376/timeline
            # Example 2 (see index 9):  https://api.github.com/repos/python/cpython/issues/17719/timeline
            if factors["Approvals"] < 0:
                factors["Approvals"] = 0
            if factors["Change_Requests"] < 0:
                factors["Change_Requests"] = 0

        elif event_type == "marked_as_duplicate":
            # Fun fact: this event was used zero (!) times in a sample of 1,000 PRs.
            pass

        elif event_type == "ready_for_review":
            # This event could be used for locating readiness,
            # however, it's seldom used. It was used only 2%
            # of the time in a sample of 1,000 PRs.
            pass

        elif event_type == "referenced":
            # According to the docs, this events only fires from references
            # in commit messages. These are counted in a more all-
            # encompassing fashion later in the function instead.
            # Docs: https://docs.github.com/en/developers/webhooks-and-events/events/issue-event-types#referenced
            pass

        elif event_type in ["added_to_project", "removed_from_project", "automatic_base_change_failed", "automatic_base_change_succeeded", "base_ref_changed", "base_ref_force_pushed", "closed", "connected", "disconnected", "convert_to_draft", "converted_note_to_issue", "deployed", "deployment_environment_changed", "head_ref_deleted", "head_ref_restored", "head_ref_force_pushed", "locked", "unlocked", "unmarked_as_duplicate", "merged", "moved_columns_in_project", "pinned", "unpinned", "reopened", "review_requested", "review_request_removed", "subscribed", "unsubscribed", "transferred", "user_blocked", "auto_rebase_enabled", "auto_squash_enabled", "base_ref_deleted", "auto_merge_disabled", "auto_merge_enabled"]:
            pass # These are the remaining possible events, which we don't care about

        else:
            return None, f"unsupported event ({event['origin']}, index {event['array_index']})"

    # Calculate the average delay between timeline events, from opening up to the last event in
    # this state.
    opening_time    : datetime.datetime = common.string_to_datetime(get_pr_json["created_at"])
    last_event_time : datetime.datetime = common.string_to_datetime(timeline[-1]["timestamp"])
    events_before_creation = _count_events_before_creation(timeline, get_pr_json)

    if len(timeline) - events_before_creation < 2:
        factors["Intermission"] = 0 # Avoid division by zero
    else:
        lifetime = (last_event_time - opening_time).total_seconds() / 60 # Convert to minutes
        # Subtract events_before_creation because we want to exclude them
        factors["Intermission"] = round(lifetime / (len(timeline) - events_before_creation - 1))

    # Collect all the text in the PR thread
    all_text = []
    all_text.extend(commit_messages)
    all_text.extend(discussion_comments)
    all_text.extend(review_comments)
    all_text.extend(commit_comments)
    all_text.append(current_title)
    if get_pr_json["body"]:  all_text.append(get_pr_json["body"])

    # Calculate the number of references to issues/PRs
    for text in all_text:

        factors["Conflicts"] += text.lower().count("conflict")

        for i in range(len(text)-1):
            # This is a very generous heuristic, but upon inspecting
            # PRs that achieve high numbers of fixes, I don't think
            # it's a big problem.
            if text[i] == "#" and text[i+1].isnumeric():
                factors["Fixes"] += 1

    factors["Events"] = len(timeline)

    if total_builds:
        factors["Build_Fail_Rate"] = failed_builds / total_builds
    else:
        factors["Build_Fail_Rate"] = 0

    return factors, ""

# Count the number of timeline events that occurred before the PR was opened.
def _count_events_before_creation(custom_timeline : [dict], pr_metadata : dict) -> int:
    event_count = 0
    creation_time : datetime.datetime = common.string_to_datetime(pr_metadata["created_at"])

    for event in custom_timeline:
        event_time : datetime.datetime = common.string_to_datetime(event["timestamp"])
        if event_time < creation_time:  event_count += 1
        else:                           break # This event happened after creation

    return event_count

def get_last_readiness_index(timeline : [dict], get_pr_json : dict) -> int:

    events_before_creation = _count_events_before_creation(timeline, get_pr_json)

    # Find out whether the creator is the only participant on the PR
    creator = get_pr_json["user"]["login"]
    creator_is_the_only_participant = True
    for i in range(events_before_creation, len(timeline)-1): # This loop range makes sure that we don't count actors of events prior to PR opening
        event = timeline[i]
        if event["actor"] != creator and event_is_participatory(event):
            creator_is_the_only_participant = False
            break

    if creator_is_the_only_participant:
        # Locate readiness one third through the PR timeline
        index = int((len(timeline) - events_before_creation) / 3)
        return index

    else:
        # Here, readiness is far more complicated to locate. We must
        # find the timeline index before a human other than the
        # PR creator authors a "participatory" event.
        for i in range(events_before_creation, len(timeline)-1):
            event = timeline[i]
            if event["actor"] != creator and event_is_participatory(event):
                return max(i-1, 0) # Don't allow a negative index

    print("Internal error: unexpected code path")
    sys.exit(1)

# def extract_pr_and_write_to_file(repo_name : str, pr_number : int, html_url : str, output_path : str):
def extract_and_write_pr(pr_url : str):

    # Get the repo and number of the PR
    group : [str] = pr_url.split("/")
    repo_name = group[3] + "/" + group[4]
    pr_number = int(group[len(group)-1])

    # API URLs
    # Docs: https://docs.github.com/en/rest/reference/pulls#get-a-pull-request
    get_pr_api_url = f"https://api.github.com/repos/{repo_name}/pulls/{pr_number}"
    # Docs: https://docs.github.com/en/rest/reference/pulls#list-commits-on-a-pull-request
    pr_list_commits_api_url = f"https://api.github.com/repos/{repo_name}/pulls/{pr_number}/commits"
    # Docs: https://docs.github.com/en/rest/reference/issues#list-timeline-events-for-an-issue
    pr_timeline_api_url = f"https://api.github.com/repos/{repo_name}/issues/{pr_number}/timeline"
    # Docs: https://docs.github.com/en/rest/pulls/comments#list-review-comments-on-a-pull-request
    pr_review_comments_api_url = f"https://api.github.com/repos/{repo_name}/pulls/{pr_number}/comments"
    # Docs: https://docs.github.com/en/rest/commits/statuses#get-the-combined-status-for-a-specific-reference
    pr_commit_status_api_url = f"https://api.github.com/repos/{repo_name}/commits/" + "{sha}/status"
    # Docs: https://docs.github.com/en/rest/commits/commits#get-a-commit
    pr_get_commit_api_url = f"https://api.github.com/repos/{repo_name}/commits/" + "{sha}"

    # Execute the API calls in parallel
    executor = concurrent.futures.ThreadPoolExecutor()
    get_pr_future             : concurrent.futures.Future = executor.submit(common.request_github_data, get_pr_api_url,             False)
    pr_list_commits_future    : concurrent.futures.Future = executor.submit(common.request_github_data, pr_list_commits_api_url,    True)
    pr_timeline_future        : concurrent.futures.Future = executor.submit(common.request_github_data, pr_timeline_api_url,        True)
    pr_review_comments_future : concurrent.futures.Future = executor.submit(common.request_github_data, pr_review_comments_api_url, True)
    get_pr_json              :  dict  = get_pr_future            .result()
    pr_list_commits_jsons    : [dict] = pr_list_commits_future   .result()
    pr_timeline_jsons        : [dict] = pr_timeline_future       .result()
    pr_review_comments_jsons : [dict] = pr_review_comments_future.result()

    # Execute additional API calls in parallel. The commit SHAs are needed
    # for these calls, hence them being executed after the other ones.
    commit_status_futures : [concurrent.futures.Future] = []
    get_commit_futures    : [concurrent.futures.Future] = []

    for pr_commit_json in pr_list_commits_jsons:
        sha  = pr_commit_json["sha"]
        commit_status_url = pr_commit_status_api_url.replace("{sha}", sha)
        get_commit_url    = pr_get_commit_api_url   .replace("{sha}", sha)
        commit_status_future : concurrent.futures.Future = executor.submit(common.request_github_data, commit_status_url, False)
        get_commit_future    : concurrent.futures.Future = executor.submit(common.request_github_data, get_commit_url, False)
        commit_status_futures.append(commit_status_future)
        get_commit_futures   .append(get_commit_future)

    commit_status_jsons : [dict] = [future.result() for future in commit_status_futures]
    get_commit_jsons    : [dict] = [future.result() for future in get_commit_futures]
    executor.shutdown()

    # Create the PR timeline
    timeline : [dict] = create_pr_timeline(pr_timeline_jsons, pr_review_comments_jsons, get_commit_jsons)

    # Find the last timeline index of the "readiness" PR state, i.e.,
    # when activity from a human other than the PR creator arises
    last_readiness_index = get_last_readiness_index(timeline, get_pr_json)

    # Find the last timeline index of the "closure" PR state, i.e.,
    # when the PR closes. This is just the last index because all
    # events after closing have been trimmed previously.
    last_closure_index = len(timeline)-1

    # Find the last timeline index of the "middle" PR state, i.e.,
    # halfway between readiness and closure
    last_middle_index = int((last_closure_index + last_readiness_index) / 2)

    def report_and_abort(message : str):
        print("Internal error: " + message)
        print("Pull: " + pr_url)
        print("Get: " + get_pr_api_url)
        print("Commits: " + pr_list_commits_api_url)
        print("Timeline: " + pr_timeline_api_url)
        print("Review comments: " + pr_review_comments_api_url)
        print("Commit status: " + pr_commit_status_api_url)
        sys.exit(1)

    # Generate the PR states
    readiness_timeline = timeline[:last_readiness_index + 1]
    middle_timeline    = timeline[:last_middle_index    + 1]
    closure_timeline   = timeline
    readiness_state, error_message = generate_state(readiness_timeline, get_pr_json, commit_status_jsons, get_commit_jsons)
    if error_message:  report_and_abort(error_message)
    middle_state,    error_message = generate_state(middle_timeline,    get_pr_json, commit_status_jsons, get_commit_jsons)
    if error_message:  report_and_abort(error_message)
    closure_state,   error_message = generate_state(closure_timeline,   get_pr_json, commit_status_jsons, get_commit_jsons)
    if error_message:  report_and_abort(error_message)

    ''' # Print the timeline. Useful for debugging.
    print(f"\tPR opened at {get_pr_json['created_at']} by {get_pr_json['user']['login']}")
    timelines = [readiness_timeline, \
                 middle_timeline[len(readiness_timeline):], \
                 closure_timeline[len(middle_timeline):] \
                ]
    for t in timelines:
        print("\t" + "-"*50)
        for e in t:
            print(f"\t{e['timestamp']} {e['actor']} {e['event']} {e['origin']} {e['array_index']}") '''

    pr_dict = {}
    pr_dict["URL"] = pr_url
    pr_dict["Merged"] = get_pr_json["merged"]
    
    for name, value in readiness_state.items():  pr_dict["Ready_"   + name] = value
    for name, value in middle_state   .items():  pr_dict["Middle_"  + name] = value
    for name, value in closure_state  .items():  pr_dict["Closure_" + name] = value

    #print(extracted_pr_dicts[0].keys())

    extracted_pr_dicts.append(pr_dict)
    #print(len(pr_dict.items()))
    #exit()

    '''
    # Create and write to the file
    f = open(output_path, "w")

    f.write(f"html_url={html_url}\n")
    f.write(f"get_url={get_pr_api_url}\n")
    f.write(f"list_commits_url={pr_list_commits_api_url}\n")
    f.write(f"timeline_url={pr_timeline_api_url}\n")
    f.write(f"review_comments_url={pr_review_comments_api_url}\n")
    f.write(f"commit_status_url={pr_commit_status_api_url}\n")
    f.write(f"get_commit_url={pr_get_commit_api_url}\n")
    f.write(f"creator={get_pr_json['user']['login']}\n")
    f.write(f"created_at={get_pr_json['created_at']}\n")
    f.write(f"merged={get_pr_json['merged']}\n")

    f.write(common.file_state_separator + "\n")
    for k,v in sorted(readiness_state.items()):  f.write(f"{k}={v}\n")

    f.write(common.file_state_separator + "\n")
    for k,v in sorted(middle_state.items()):     f.write(f"{k}={v}\n")

    f.write(common.file_state_separator + "\n")
    for k,v in sorted(closure_state.items()):    f.write(f"{k}={v}\n")

    f.close()

    print("    Wrote data to " + output_path)
    '''

# Make the output directory if it does not exist
# if not os.path.exists(output_path):  os.mkdir(output_path)

for i, pr_url in enumerate(pr_urls_to_extract):
    print(f"Extracting {pr_url}...")
    extract_and_write_pr(pr_url)
    print(f"Progress: {(i+1) / len(pr_urls_to_extract) :.3%}")

common.write_dicts_to_csv(extraction_file_path, extracted_pr_dicts)

print("Done.")
