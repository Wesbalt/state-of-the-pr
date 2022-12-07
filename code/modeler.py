import common, sys, os, random, scipy.stats, pprint, itertools, math, sklearn.feature_selection, sklearn.preprocessing, sklearn.model_selection, sklearn.ensemble, sklearn.tree, sklearn.naive_bayes, sklearn.linear_model, sklearn.svm, numpy, sklearn.inspection

# TODO Add more descriptive output
# TODO Comment more
# TODO Remove support for multiple algorithms
# TODO Create model files

# Used for colored console output. Make these empty strings if you don't want coloring.
ANSI_RESET  = "\033[0m"
ANSI_RED    = "\033[91m"
ANSI_GREEN  = "\033[92m"

if len(sys.argv) != 2:
	print("Usage: py %s <input>" % sys.argv[0])
	sys.exit(1)

input_path = sys.argv[1] # A directory containing the extraction files
extraction_filenames = os.listdir(input_path)
print(f"Found {len(extraction_filenames)} extraction files")

# Set this to non-zero if you would like to extract a sample
sample_size = 0
if sample_size:
    extraction_filenames = random.sample(extraction_filenames, sample_size)
    print(f"Sample of size {sample_size} taken")

print("Reading extraction files... (Takes a while if cold)")

# String lists that will contain the feature names
all_feature_names       : [str] = []
readiness_feature_names : [str] = []
middle_feature_names    : [str] = []
closure_feature_names   : [str] = []

# Float matrices that will contain the feature values (one sample per row, one feature per column)
readiness_X : numpy.array = None
middle_X    : numpy.array = None
closure_X   : numpy.array = None

# Int list that will contain the labels (1 means merged, 0 means non-merged)
y = numpy.empty(0)

# Read the extraction files
first_iteration = True
for i, extraction_filename in enumerate(extraction_filenames):

    # Read extraction file
    filepath = os.path.join(input_path, extraction_filename)
    metadata, readiness_sample, middle_sample, closure_sample = common.read_extraction_file(filepath)

    if first_iteration:
        first_iteration = False

        # Instantiate feature name lists
        all_feature_names       = [name for name, _ in readiness_sample]
        readiness_feature_names = all_feature_names
        middle_feature_names    = all_feature_names
        closure_feature_names   = all_feature_names

        # Instantiate feature matrices
        matrix_shape = (len(extraction_filenames), len(all_feature_names))
        readiness_X = numpy.ndarray(matrix_shape)
        middle_X    = readiness_X.copy()
        closure_X   = readiness_X.copy()

    # Get the feature values
    readiness_X[i] = [value for _, value in readiness_sample]
    middle_X   [i] = [value for _, value in    middle_sample]
    closure_X  [i] = [value for _, value in   closure_sample]

    # Add the label
    merged = int(common.string_to_bool(metadata["merged"]))
    y = numpy.append(y, merged)

print("Extraction files read")

def _transform(X : numpy.array) -> numpy.array:

    # Log transform
    for sample in X:
        for i, value in enumerate(sample):
            if value == 0:  value = 0.5
            value = math.log(value)
            sample[i] = value

    # Standardize
    scaler = sklearn.preprocessing.StandardScaler(with_mean=True, with_std=True)
    standardized_X = scaler.fit_transform(X)

    return standardized_X

readiness_X = _transform(readiness_X)
middle_X    = _transform(   middle_X)
closure_X   = _transform(  closure_X)

# all_states_X = numpy.concatenate((readiness_X, middle_X, closure_X))
# all_states_X = numpy.concatenate((closure_X))
# print(all_states_X)
# print(all_states_X.shape)
# sys.exit()

def _filter_features(feature_names : [str], X : numpy.array) -> ([str], numpy.array):
    global readiness_X, middle_X, closure_X, closure_feature_names # TODO Remove me

    print("Calculating Spearman's rank correlation matrix...")

    # Transpose the features, making it so each row contains all values of a particular feature
    transposed_X = numpy.transpose(X)

    # Thresholds for judging correlation severity
    strong_correlation_threshold   = 0.70 # Scores below this indicate moderate correlation
    moderate_correlation_threshold = 0.35 # Scores below this indicate weak     correlation

    p_threshold = 0.05 # Threshold for statistical significance

    # Calculate the correlation matrix
    correlation_matrix : [[(float, float)]] = []
    strongly_correlated_pairs : [(int, int)] = []
    for row in range(len(feature_names)):
        correlation_matrix.append([])
        for column in range(len(feature_names)):
            values_a = transposed_X[row]
            values_b = transposed_X[column]
            score, p_value = scipy.stats.spearmanr(values_a, values_b)
            correlation_matrix[row].append((score, p_value))

    # Print correlation matrix
    print("Correlation matrix:")
    print("(Scores colored according to correlation severity. Statistically insignificant and redundant scores omitted.)\n")
    cell_length = len("-0.00") # This is the visually longest value that can be printed
    for row in range(len(correlation_matrix)):
        for column in range(row):
            score, p_value = correlation_matrix[row][column]
            if p_value > p_threshold:
                # Statistically insignificant, print an empty space
                print(" " * cell_length, end=" ")
            else:
                ansi_color = ""
                if abs(score) >= strong_correlation_threshold:
                    ansi_color = ANSI_RED
                elif abs(score) >= moderate_correlation_threshold:
                    ansi_color = "" # No coloring
                else: # Weak correlation
                    ansi_color = ANSI_GREEN
                cell_string = ("{:" + str(cell_length) + ".2f}").format(score) # Pad and round the score
                print(ansi_color + cell_string + ANSI_RESET, end=" ")
        print(feature_names[row] + "\n")

    # For every strongly correlated pair, find and report the feature with the largest mean correlation
    indices_to_drop = set()
    for i in range(len(feature_names)):
        for j in range(i): # Iterate up to the row index to avoid duplicates
            score, p_value = correlation_matrix[i][j]

            if abs(score) >= strong_correlation_threshold and p_value <= p_threshold:

                # The features on index i and j are strongly correlated
                scores_i = [abs(score) for score, p_value in correlation_matrix[i] if p_value <= p_threshold]
                scores_j = [abs(score) for score, p_value in correlation_matrix[j] if p_value <= p_threshold]
                mean_i   = sum(scores_i) / len(scores_i)
                mean_j   = sum(scores_j) / len(scores_j)

                if mean_i > mean_j:  indices_to_drop.add(i)
                else:                indices_to_drop.add(j)

    # Report filtered features
    print("Dropping the following features: ", end="")
    print(", ".join([name for i, name in enumerate(feature_names) if i in indices_to_drop]))

    # Filter feature names and values
    indices_to_drop = list(indices_to_drop)
    feature_names = numpy.delete(feature_names, indices_to_drop).tolist()
    #X             = numpy.delete(X,             indices_to_drop, axis=1) # TODO Uncomment me

    readiness_X = numpy.delete(readiness_X, indices_to_drop, axis=1)
    middle_X    = numpy.delete(   middle_X, indices_to_drop, axis=1)
    closure_X   = numpy.delete(  closure_X, indices_to_drop, axis=1)

    closure_feature_names = feature_names

    #return feature_names, X # TODO Uncomment me

# Filter factors of low variance and strong correlation
border_length = 30
#print("-" * border_length + " Readiness " + "-" * border_length)
_filter_features(closure_feature_names, closure_X)
# TODO Uncomment me
#readiness_feature_names, readiness_X = _filter_features(readiness_feature_names, readiness_X)
#print("-" * border_length + " Middle " + "-" * border_length)
#middle_feature_names, middle_X = _filter_features(middle_feature_names, middle_X)
#print("-" * border_length + " Closure " + "-" * border_length)
#closure_feature_names, closure_X = _filter_features(closure_feature_names, closure_X)

kfold_split_count = 10
kfold = sklearn.model_selection.StratifiedKFold(n_splits=kfold_split_count, shuffle=True)

def _train_and_evaluate(classifier : object, X_for_training, X_for_testing) -> ([float], [float]):

    # A matrix containing all metrics over each fold. One column per metric and one row per fold.
    all_scores = []

    for train_indices, test_indices in kfold.split(X_for_training, y):

        X_train = X_for_training[train_indices] # features to train on
        X_test  = X_for_testing [ test_indices] # features to  test on
        y_train = y[train_indices] # merge outcomes to train on
        y_test  = y[ test_indices] # merge outcomes to  test on

        classifier.fit(X_train, y_train)
        y_prediction = classifier.predict(X_test)
        tn, fp, fn, tp = sklearn.metrics.confusion_matrix(y_test, y_prediction).ravel()

        acc            = (tp + tn) / (tp + tn + fp + fn)
        merge_prec     = tp / (tp + fp)
        non_merge_prec = tn / (tn + fn)
        merge_rec      = tp / (tp + fn) # A.k.a. sensitivity
        non_merge_rec  = tn / (tn + fp) # A.k.a. specificity
        merge_f1       = 2 *     merge_prec *     merge_rec / (    merge_prec +     merge_rec)
        non_merge_f1   = 2 * non_merge_prec * non_merge_rec / (non_merge_prec + non_merge_rec)
        auc            = sklearn.metrics.roc_auc_score(y_test, y_prediction)
        mcc            = (tp*tn - fp*fn) / math.sqrt((tp+fp) * (tp+fn) * (tn+fp) * (tn+fn))

        scores = [
            acc,
            merge_prec,
            non_merge_prec,
            merge_rec,
            non_merge_rec,
            merge_f1,
            non_merge_f1,
            auc,
            mcc,
        ]

        all_scores.append(scores)

    return numpy.mean(all_scores, axis=0).tolist(), numpy.std(all_scores, axis=0).tolist()

classifier_dict = {
    "ada"    : ("AdaBoost",             sklearn.ensemble.AdaBoostClassifier),
	"bag"    : ("Bagging",              sklearn.ensemble.BaggingClassifier),
    "tree"   : ("Decision Tree",        sklearn.tree.DecisionTreeClassifier),
	"bayes"  : ("Gaussian Naive Bayes", sklearn.naive_bayes.GaussianNB),
    "svm"    : ("Linear SVM",           sklearn.svm.LinearSVC),
	"logreg" : ("Logistic Regression",  sklearn.linear_model.LogisticRegression),
    "forest" : ("Random Forest",        sklearn.ensemble.RandomForestClassifier),
}

classifier_keyword = "logreg"
classifier_name    = classifier_dict[classifier_keyword][0]
classifier_class   = classifier_dict[classifier_keyword][1]
classifier_object  = classifier_class()
if classifier_class in [sklearn.linear_model.LogisticRegression, sklearn.svm.LinearSVC]:
    classifier_object.set_params(max_iter=1e9)

print(classifier_name + " classifier chosen")

table_headers = "ACC | Merge PREC | Non-merge PREC | Merge REC | Non-merge REC | Merge F1 | Non-merge F1 | AUC | MCC"
print("-" * len(table_headers))
print(table_headers)
print("-" * len(table_headers))

scores_from_all_states : [[float]] = []

for X in [readiness_X, middle_X, closure_X]:

    scores, stdevs = _train_and_evaluate(classifier_object, closure_X, X) # Always train on closure data, predict on variable data
    score_strings = [" %.2f " % score for score in scores]
    print(" | ".join(score_strings))
    scores_from_all_states.append(scores)

mean_scores   = numpy.mean(scores_from_all_states, axis=0).tolist()
mean_accuracy = mean_scores[0]

mean_strings = ["(%.2f)" % mean for mean in mean_scores]
print(" | ".join(mean_strings))

readiness_accuracy, middle_accuracy, closure_accuracy = numpy.array(scores_from_all_states)[:,0]

print("-" * len(table_headers))

'''highest_mean_index = 0
for i in range(len(prediction_results)):
    this_mean            = prediction_results[i][3]
    current_highest_mean = prediction_results[highest_mean_index][3]
    if this_mean > current_highest_mean:  highest_mean_index = i

classifier_name, classifier_object, accuracy_scores, _ = prediction_results[highest_mean_index]'''

# Permutation importance
'''foo = sklearn.inspection.permutation_importance(classifier_object, readiness_X, y)
readiness_thingies = [ttt for ttt in zip(readiness_feature_names, foo.importances_mean, foo.importances_std)]
readiness_thingies.sort(key = lambda x: x[1], reverse = True)
print("readiness")
for name, importance, std in readiness_thingies:
    print(f"{name} {importance} {std}")

foo = sklearn.inspection.permutation_importance(classifier_object, middle_X, y)
middle_thingies = [ttt for ttt in zip(middle_feature_names, foo.importances_mean, foo.importances_std)]
middle_thingies.sort(key = lambda x: x[1], reverse = True)
print("middle")
for name, importance, std in middle_thingies:
    print(f"{name} {importance} {std}")

foo = sklearn.inspection.permutation_importance(classifier_object, closure_X, y)
closure_thingies = [ttt for ttt in zip(closure_feature_names, foo.importances_mean, foo.importances_std)]
closure_thingies.sort(key = lambda x: x[1], reverse = True)
print("closure")
for name, importance, std in closure_thingies:
    print(f"{name} {importance} {std}")'''

def _get_feature_importance(classifier : object, X : numpy.array, feature_index : int, baseline_accuracy : float):
    X_for_training = numpy.delete(closure_X, feature_index, axis=1)
    X_for_testing  = numpy.delete(        X, feature_index, axis=1)
    scores, stdevs = _train_and_evaluate(classifier, X_for_training, X_for_testing)
    accuracy_score = scores[0]
    accuracy_stdev = stdevs[0]
    accuracy_change_value = baseline_accuracy - accuracy_score
    return accuracy_change_value, accuracy_stdev

table_headers = "Feature | Importance | Importance (stdev)"
print("-" * len(table_headers))
print(table_headers)
print("-" * len(table_headers))

longest_feature_name_length = len(max(closure_feature_names, key=len))

# thingies = [[],[],[]]

for feature_index, feature_name in enumerate(closure_feature_names):

    for i in range(3):
        state_X        = [readiness_X, middle_X, closure_X][i]
        state_accuracy = [readiness_accuracy, middle_accuracy, closure_accuracy][i]

        if i == 0:
            # Print the factor name
            print(feature_name.ljust(longest_feature_name_length), end=" | ")
        else:
            # Pad the row to line up the column with the factor name
            print(" " * longest_feature_name_length, end=" | ")

        importance, stdev = _get_feature_importance(classifier_object, state_X, feature_index, state_accuracy)
        print("%.7f" % importance + " | " + str(stdev))

        # thingies[i].append((feature_name, importance))

    print("-" * len(table_headers))

'''
for state_name, state_thingies in zip(["readiness", "middle", "closure"], thingies):
    state_thingies.sort(key = lambda x: x[1], reverse = True)
    print(state_name)
    for name, importance in state_thingies:
        print(name, importance)
'''

print("Done.")
