"""Description:- In this piece of code we are pre processing our dataset to get the required batches of Bag of words to train the model for one out of twenty
task at a time. """

from __future__ import absolute_import
from __future__ import print_function

from data_utils import load_task, vectorize_data
from sklearn import cross_validation, metrics
from hashed_mem_nw import Hashed_Mem_Nw
from itertools import chain
from six.moves import range

import tensorflow as tf
import numpy as np
from hashed_mem_nw import zero_nil_slot, add_gradient_noise

def get_grads_and_vars(model):
    max_grad_norm = 20.0
    gr_vars = optimizer.compute_gradients(model.loss_op)

    gr_vars = [(tf.clip_by_norm(g, max_grad_norm), v)
                      for g, v in gr_vars if g is not None]
    gr_vars = [(add_gradient_noise(g), v) for g, v in gr_vars]
    nil_gv = []
    for g, v in gr_vars:
        if v.name in model._nil_vars:
            nil_gv.append((zero_nil_slot(g), v))
        else:
            nil_gv.append((g, v))
    return nil_gv

# Below is the description of the default values of parameters that we need to train the model.We can override these default values from command line. 

epsilon = 0.1
l2_lambda = 0.1
learning_rate = 0.001

keep_prob = 1.0
evaluation_interval = 50
batch_size = 32
feature_size = 40
hops = 3
epochs = 100
embedding_size = 30
memory_size = 20
task_id = 1
data_dir = "data/tasks_1-20_v1-2/en/"
reader = "bow" # bow / simple_gru
allow_soft_placement = True
log_device_placement = False
output_file = 'single_scores.csv'


# Below two lines load the test and train data for a particular task in tokenized form, where each data tuple has story, related question and its answer.
train, test = load_task(data_dir, task_id)
data = train + test

# from the words we got from dataset below lines makes a dictionary(vocab-index on number) and a reverse dictionary (word_idx-indexed on words).
vocab = sorted(reduce(lambda x, y: x | y, (set(list(chain.from_iterable(s)) + q + a) for s, q, a in data)))
word_idx = dict((c, i + 1) for i, c in enumerate(vocab))

# Below lines calculate the maximum story size and sentence size to get dimension of vectors need to be created for bag of words representation.
max_story_size = max(map(len, (s for s, _, _ in data)))
mean_story_size = int(np.mean(map(len, (s for s, _, _ in data))))
sentence_size = max(map(len, chain.from_iterable(s for s, _, _ in data)))
query_size = max(map(len, (q for _, q, _ in data)))
memory_size = min(memory_size, max_story_size)
vocab_size = len(word_idx) + 1 # +1 for nil word
sentence_size = max(query_size, sentence_size) 



# Below lines give the vectorized form of the dataset.
S, Q, A = vectorize_data(train, word_idx, sentence_size, memory_size)
trainS, valS, trainQ, valQ, trainA, valA = cross_validation.train_test_split(S, Q, A, test_size=.1) #Partitioning train dataset for validation and train using sklearn library function
testS, testQ, testA = vectorize_data(test, word_idx, sentence_size, memory_size)

n_train = trainS.shape[0]
n_test = testS.shape[0]
n_val = valS.shape[0]


# As the vector for each answer will have only one cell as one so we are finding argmax to get a dense matrix to compare the output generated by model.
train_labels = np.argmax(trainA, axis=1)
test_labels = np.argmax(testA, axis=1)
val_labels = np.argmax(valA, axis=1)

#Below line generates random batches of given batch size.
batch_size = batch_size
batches = zip(range(0, n_train-batch_size, batch_size), range(batch_size, n_train, batch_size))

# Defining computation graph and placeholders for tensor flow
with tf.Graph().as_default():
    session_conf = tf.ConfigProto(
        allow_soft_placement=allow_soft_placement,
        log_device_placement=log_device_placement)

    global_step = tf.Variable(0, name="global_step", trainable=False)
    # decay learning rate
    starter_learning_rate = learning_rate
    learning_rate = tf.train.exponential_decay(starter_learning_rate, global_step, 20000, 0.96, staircase=True)

    optimizer = tf.train.AdamOptimizer(learning_rate=learning_rate, epsilon=epsilon)

    with tf.Session() as sess:
        
        # Getting the key-value hashed model initial placeholders and computation network generated.
        model = Hashed_Mem_Nw( vocab_size=vocab_size,
                          query_size=sentence_size, story_size=sentence_size, memory_key_size=memory_size,
                         memory_value_size=memory_size,
                          embedding_size=embedding_size, reader=reader,
                          l2_lambda=l2_lambda)
        nil_grads_and_vars = get_grads_and_vars(model)
       

        train_op = optimizer.apply_gradients(nil_grads_and_vars, name="train_op", global_step=global_step)
        sess.run(tf.initialize_all_variables()) # Initializing all the variables declared for tensorflow computation graph.
        #Declaring a saver to take snapshot of trained model at regular time interval.
        saver = tf.train.Saver()

        # Below method feeds the training batch values to model and predicts the output after training.
        def train_step(s, q, a):
            feed_dict = {
                model._memory_value: s,
                model._query: q,
                model._memory_key: s,
                model._labels: a,
                model.keep_prob: keep_prob
            }
            _, step, predict_op = sess.run([train_op, global_step, model.predict_op], feed_dict)
            return predict_op

        #Below method is used for feed the test data to model and get the predicted output from model.
        def test_step(s, q):
            feed_dict = {
                model._query: q,
                model._memory_key: s,
                model._memory_value: s,
                model.keep_prob: 1
            }
            preds = sess.run(model.predict_op, feed_dict)
            return preds

        #Here we starts training and validating the model for specified no. of epochs. 
        for t in range(1, epochs+1):
            np.random.shuffle(batches)# Get the shuffled batch
            train_preds = []
            # Training the model from the begining till the end of train dataset by creating batches of batch_size
            for start in range(0, n_train, batch_size):
                end = start + batch_size
                s = trainS[start:end]
                q = trainQ[start:end]
                a = trainA[start:end]
                predict_op = train_step(s, q, a)
                train_preds += list(predict_op)

            #Calculating the training score after each epoch on training dataset   
            train_acc = metrics.accuracy_score(np.array(train_preds), train_labels)
            print('-----------------------')
            print('Epoch', t)
            print('Training Accuracy: {0:.2f}'.format(train_acc))
            print('-----------------------')
            
            #Evaluating the model after specified no. of epoch on validation dataset.    
            if t % evaluation_interval == 0:
                val_preds = test_step(valS, valQ)
                val_acc = metrics.accuracy_score(np.array(val_preds), val_labels)
                #print (val_preds)
                print('-----------------------')
                print('Epoch', t)
                print('Validation Accuracy:', val_acc)
                print('-----------------------')
                #Saving the snapshot of model after validation.
                save_path = saver.save(sess, "./models/models-1k/task-{}/model.ckpt".format(task_id))
                print("Model saved in file: %s" % save_path)
                
        # test on train dataset after completing all epoch.
        train_preds = test_step(trainS, trainQ)
        train_acc = metrics.accuracy_score(train_labels, train_preds)
        train_acc = '{0:.2f}'.format(train_acc)
        # evaluating on validation dataset after completing training.
        val_preds = test_step(valS, valQ)
        val_acc = metrics.accuracy_score(val_labels, val_preds)
        val_acc = '{0:.2f}'.format(val_acc)
        # testing dataset evaluation after completion of training.
        test_preds = test_step(testS, testQ)
        test_acc = metrics.accuracy_score(test_labels, test_preds)
        test_acc = '{0:.2f}'.format(test_acc)
        print("Testing Accuracy: {}".format(test_acc))
        print('Writing final results to {}'.format(output_file))
        with open(output_file, 'a') as f:
            f.write('{}, {}, {}, {}\n'.format(task_id, test_acc, train_acc, val_acc))

