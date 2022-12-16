import requests, traceback, time, datetime, sys, typing, pprint, csv

file_state_separator = "-"*50 # Used as a separator between different PR states in extraction files

def string_to_bool(s : str) -> bool:
    if s.lower() ==  "true":  return True
    if s.lower() == "false":  return False
    print(f"Could not parse \"{s}\" to bool")
    sys.exit(1)

def string_to_datetime(timestamp_string : str) -> datetime.datetime:
	return datetime.datetime.strptime(timestamp_string, "%Y-%m-%dT%H:%M:%SZ")

def read_csv_as_dicts(path : str) -> [dict]:
    f = open(path, "r", newline="")
    csv_reader = csv.DictReader(f) # The dict field names are determined by the first row in the file
    dicts = [row_dict for row_dict in csv_reader]
    f.close()
    return dicts

def write_dicts_to_csv(path : str, dicts : [dict]):

    # Get the field names and make sure every dictionary has identical keys
    fieldnames = dicts[0].keys() # Choose the field names in the 1st dict
    for d in dicts:
        if d.keys() != fieldnames:
            # TODO Improve error message
            print("Non-matching dictionary keys")
            exit()

    f = open(path, "w", newline="") # This truncates the file
    csv_writer = csv.DictWriter(f, fieldnames)
    csv_writer.writeheader()
    csv_writer.writerows(dicts)
    f.close()

'''
Return the lines from a text file, removing comments if desired
'''
def read_file(path : str, remove_comments : bool) -> [str]:
    f     = open(path, "r", encoding="utf-8")
    lines = f.read().splitlines()
    f.close()

    if not remove_comments:  return lines

    # Remove commented lines and contents
    uncommented_lines = []
    for l in lines:
        l = l.split("#")[0] # Remove everything after '#' which is the comment token
        l = l.strip() # Remove leading and trailing whitespace
        if l != "":  uncommented_lines.append(l)

    return uncommented_lines

'''
Read an extraction file, returning the metadata and factors from the PR states.
The factor lists are ordered according to the original file contents. See the
extraction directory for reference on the file syntax.

Return:
    dict           - metadata
    [(str, float)] - factors from the readiness state
    [(str, float)] - factors from the middle    state
    [(str, float)] - factors from the closure   state
'''
def read_extraction_file(path : str) -> (dict, [(str, float)], [(str, float)], [(str, float)]):
    lines = read_file(path, False)

    # Read metadata
    metadata = {}
    while lines:
        line = lines.pop(0)
        if line == file_state_separator:  break
        key, value = line.split("=", 1) # Splits at first occurrence
        metadata[key] = value

    # Define a helper function to read factors
    def read_factors() -> [(str, float)]:
        factors : [()] = []
        while lines:
            line = lines.pop(0)
            if line == file_state_separator:  break
            name, value = line.split("=", 1) # Splits at first occurrence
            pair = (name, float(value))
            factors.append(pair)
        return factors

    # Read factors
    readiness_factors = read_factors()
    middle_factors    = read_factors()
    closure_factors   = read_factors()

    return metadata, readiness_factors, middle_factors, closure_factors

tokens = []
token_index = 0
def get_token() -> str:
	global token_index

	token = tokens[token_index]

	# Cycle through tokens
	token_index += 1
	if token_index >= len(tokens):  token_index = 0

	return token

def _request_json(url : str) -> ([dict], int, str):
	json = None
	code = -1
	# Cycle and try all tokens if one exceeds the GitHub API rate limit (403)
	for _ in range(len(tokens)):
		token = get_token()
		resp : requests.Response = requests.get(url, headers={"authorization": "token " + token})
		json : [dict] = resp.json()
		code = resp.status_code
		if code != 403:  break

	return json, code, resp.reason

def _nap(message : str, nap_time_seconds : int):
    print(f"{message}, napping {nap_time_seconds} seconds...")
    time.sleep(nap_time_seconds)

def _nap_or_exit_on_exception(exception : Exception, consecutive_exceptions : int):
    print("Exception raised during request:")
    print(traceback.print_exc())
    if consecutive_exceptions >= 10:
        print("Too many exceptions in a row")
        sys.exit(1)
    _nap("Exception raised", 10)

# Return the response and a flag depending on if a rare edge
# case happened, see comment inside function for detail.
def _single_github_api_request(url : str, nap_time_seconds : int) -> ([dict], bool):

    consecutive_exceptions = 0
    while True:

        json : [dict] = []
        code   = -1
        reason = ""
		
        try:
            json, code, reason = _request_json(url)
        except Exception as e:
            consecutive_exceptions += 1
            _nap_or_exit_on_exception(e, consecutive_exceptions)
            continue

        if code == 200:
            return json, False

        elif code == 403:
            # RARE EDGE CASE: 403 nearly always means the GitHub API rate limit was exceeded so we
            # should nap and try again. However, the following 403 is given for this request:
            #   Request: https://api.github.com/repos/torvalds/linux/contributors
            #   Response: 403 "The history or contributor list is too large to list contributors for this repository via the API."
            # The hacky if statement below is to detect this stupid
            # edge case and avoid sleeping unnecessarily. Sigh.
            if "too large to list contributors" in json["message"].lower():
                return [], True
            else:
                # The edge case did not happen, nap and retry the request
                _nap("API rate limit exceeded", nap_time_seconds)

        elif code >= 400 and code < 500:
            print(f"Client error ({code} {reason})")
            print("URL: " + url)
            _nap(reason, 10)

        elif code >= 500 and code < 600:
            print(f"Server error ({code} {reason})")
            print("URL: " + url)
            _nap(reason, 10)

        else:
            print(f"Internal error: unexpected response ({code} {reason})")
            print("URL: " + url)
            sys.exit(1)

    print("Internal error: unexpected code path")
    sys.exit(1)

'''
Send the GitHub API request and return the JSON response(s), waiting for the API rate
limit reset if necessary.

Return:
  typing.Any - the API response(s).
               if pagination is used, a list of JSON objects (type [dict]).
               if not, return a JSON object (type dict).
'''
def request_github_data(api_url : str, use_pagination : bool) -> typing.Any:

    if not use_pagination:
        json, _ = _single_github_api_request(api_url, 60)
        return json

    else:
        items_per_page   = 100 # Max 100
        page_number      = 1 # One indexed
        api_url_template = api_url + "?per_page=%d&page=%d"
        complete_json    = []

        while True:
            api_url = api_url_template % (items_per_page, page_number)
            json, _ = _single_github_api_request(api_url, 60)
            complete_json.extend(json)
            # Break if we get less items than requested, for there is nothing more to request
            if len(json) < items_per_page:  break
            page_number += 1

        return complete_json

'''
Uses the GitHub Search API and returns up to the desired amount of results.
Uses pagination for complete results.

Set limit to -1 to search limitlessly, but keep in mind GitHub only stores
up to 1000 search results anyway.

Docs: https://docs.github.com/en/rest/reference/search
'''
def search_github(url : str, query : str, limit : int) -> [dict]:

    items_per_page = 100 # Max 100
    page_number    = 1 # One indexed
    url_template   = f"{url}?q={query}&per_page={items_per_page}&page="
    complete_json  = []

    while True:
        url = url_template + str(page_number)
        json, _ = _single_github_api_request(url, 60)

        complete_json.extend(json["items"])

        # Break if we have reached the desired request limit
        if limit != -1 and len(complete_json) >= limit:  break
        # Break if we exceed GitHub's own search result limit
        if len(complete_json) >= 1000:  break
        # Break if we get less items than requested (meaning that there is no more to request)
        if len(json["items"]) < items_per_page:  break

        page_number += 1

    if limit == -1:  return complete_json
    else:            return complete_json[:limit] # Trim off excess if a limit was desired

def user_is_human(user_json : dict) -> bool:
    user_name = user_json["login"].lower()
    user_type = user_json["type"] .lower()

    return user_type == "user" and "bot" not in user_name

'''
Return the actor of the GitHub event and whether they are a user.
Return ("", False) for deleted accounts.

The following events are supported:
Timeline events: https://docs.github.com/en/developers/webhooks-and-events/events/issue-event-types
Review comments: https://docs.github.com/en/rest/pulls/comments#list-review-comments-on-a-pull-request

There is one caveat. This function fails on "committed" events
because they lack the "login" and "type" fields. This data must
be added before-hand to the "committer" field.
'''
def get_event_actor(event_json : dict) -> (str, bool):

    user_data : dict = None
    if "actor" in event_json:
        user_data = event_json["actor"]

    elif "user" in event_json:
        user_data = event_json["user"]

    elif "committer" in event_json:
        user_data = event_json["committer"]

    else:
        print("Internal error: could not find actor")
        pprint.pprint(event_json)
        sys.exit(1)

    if user_data: # Account exists
        actor = user_data["login"]
        # The "type" field is wrong sometimes, marking bots
        # as humans, so check for the "bot" substring also
        is_user = user_data["type"].lower() == "user" and "bot" not in actor.lower()
        return actor, is_user

    else: # Account deleted
        return "", False

''' Returns -1 if no digits were found '''
def _read_digits_until_char(string : str, delimiter : str) -> int:
    if len(delimiter) != 1:
        print(f"Internal error: unexpected delimiter (wanted a string of length 1, got \"{delimiter}\")")
        sys.exit(1)

    digits = ""
    for char in string:
        if char == delimiter:  break
        if char.isdigit():  digits += char

    if len(digits):  return int(digits)
    else:            return -1

def _request_html(url : str) -> str:
    consecutive_exceptions = 0
    while True:
        
        try:
            response : requests.Response = requests.get(url)
        except Exception as e:
            consecutive_exceptions += 1
            _nap_or_exit_on_exception(e, consecutive_exceptions)
            continue
        
        if response.status_code == 429:
            _nap("Too many GET requests", 10)
        else:
            return str(response.content)

def get_commit_count(repo : str) -> int:
    '''
    Example:
    URL: https://github.com/netdata/netdata
    HTML code snippet of interest:
    <span class="d-none d-sm-inline">
        <strong>
            13,577   <--- This is what we want!
        </strong>
        <span aria-label="Commits on master" class="color-fg-muted d-none d-lg-inline">
            commits
        </span>
    </span>
    '''

    html_string = _request_html("https://github.com/" + repo)
    html_string = html_string.split('aria-label="Commits on ', 1)[0]
    html_string = html_string.rsplit("<strong>", 1)[1]

    return _read_digits_until_char(html_string, "<")

def get_contributor_count(repo : str) -> int:
    '''
	Example:
	URL: https://github.com/netdata/netdata
    HTML code snippet of interest:
    <h2 class="h4 mb-3">
        <a href="/netdata/netdata/graphs/contributors" data-view-component="true" class="Link--primary no-underline">
            Contributors
            <span title="505" data-view-component="true" class="Counter">
                505   <--- This is what we want!
            </span>
        </a>
    </h2>
    '''

    html_string = _request_html("https://github.com/" + repo)
    html_string = html_string.rsplit('class="Link--primary no-underline"', 1)[1]
    html_string = html_string.split("/span>")[0]
    html_string = html_string.rsplit(">", 1)[1]

    count = _read_digits_until_char(html_string, "<")
    if count == -1:  return 0 # This means the HTML had no contributor section due to having zero contributors
    else:            return count

def get_closed_pull_count(repo : str) -> int:
    '''
    Example:
    URL: https://github.com/netdata/netdata/pulls
    HTML code snippet of interest:
    <a href="/dotnet/efcore/issues?q=is%3Apr+is%3Aclosed" class="btn-link" data-ga-click="Pull Requests, Table state, Closed">
        <svg aria-hidden="true" height="16" viewBox="0 0 16 16" version="1.1" width="16" data-vie   w-component="true" class="octicon octicon-check">
            <path fill-rule="evenodd" d="M13.78 4.22a.75.75 0 010 1.06l-7.25 7.25a.75.75 0 01-1.06 0L2.22 9.28a.75.75 0 011 .06-1.06L6 10.94l6.72-6.72a.75.75 0 011.06 0z">
            </path>
        </svg>
        9,872 Closed   <--- This is what we want!
    </a>
    '''

    html_string = _request_html("https://github.com/" + repo + "/pulls")
    html_string = html_string.split("Pull Requests, Table state, Closed", 1)[1]
    html_string = html_string.split("</svg>", 1)[1]
    return _read_digits_until_char(html_string, "C")
