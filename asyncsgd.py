import tensorflow as tf
import os

tf.app.flags.DEFINE_integer("task_index", 0, "Index of the worker task")
FLAGS = tf.app.flags.FLAGS

worker_num = 5
num_features = 33762578

iterate_num = 1000
# number of test data in the test set
test_num = 500
# when to run the testing data
break_point = 100
g = tf.Graph()

input_producers = [
    ["./data/tfrecords00", "./data/tfrecords01", "./data/tfrecords02", "./data/tfrecords03", "./data/tfrecords04"],
    ["./data/tfrecords05", "./data/tfrecords06", "./data/tfrecords07", "./data/tfrecords08", "./data/tfrecords09"],
    ["./data/tfrecords10", "./data/tfrecords11", "./data/tfrecords12", "./data/tfrecords13", "./data/tfrecords14"],
    ["./data/tfrecords15", "./data/tfrecords16", "./data/tfrecords17", "./data/tfrecords18", "./data/tfrecords19"],
    ["./data/tfrecords20", "./data/tfrecords21"],
    ["./data/tfrecords22"]
]

with g.as_default():

    # creating a model variable on task 0. This is a process running on node vm-48-1
    with tf.device("/job:worker/task:0"):
        w = tf.Variable(tf.zeros([num_features]), name="model")


    # 1. update indice to parameter server
    with tf.device("/job:worker/task:%d" % FLAGS.task_index):
        filename_queue = tf.train.string_input_producer(input_producers[FLAGS.task_index], num_epochs=None)
        reader = tf.TFRecordReader()
        _, serialized_example = reader.read(filename_queue)
        features = tf.parse_single_example(serialized_example,
                                           features={'label': tf.FixedLenFeature([1], dtype=tf.int64),
                                                     'index': tf.VarLenFeature(dtype=tf.int64),
                                                     'value': tf.VarLenFeature(dtype=tf.float32)})
        label = features['label']
        index = features['index']
        value = features['value']

    # 2. push dense weights to all workers
    with tf.device("/job:worker/task:0"):
        weight = tf.gather(w, index.values)

    # 3. calculate gradients
    with tf.device("/job:worker/task:%d" % FLAGS.task_index):
        y = tf.cast(label, tf.float32)[0]
        x = value.values
        a = tf.mul(weight, x)
        b = tf.reduce_sum(a)
        c = tf.sigmoid(tf.mul(y, b))
        d = tf.mul(y, c-1)
        local_gradient = tf.mul(d, x)

    # 4. update gradients
    with tf.device("/job:worker/task:0"):
        ggg = local_gradient
        w = tf.scatter_sub(w, index.values, local_gradient)


    # 5. calculate test error
    with tf.device("/job:worker/task:0"):
        filename_queue = tf.train.string_input_producer(input_producers[5], num_epochs=None)
        reader = tf.TFRecordReader()
        _, serialized_example = reader.read(filename_queue)
        features = tf.parse_single_example(serialized_example,
                                           features={'label': tf.FixedLenFeature([1], dtype=tf.int64),
                                                     'index': tf.VarLenFeature(dtype=tf.int64),
                                                     'value': tf.VarLenFeature(dtype=tf.float32)})
        label = features['label']
        index = features['index']
        value = features['value']
        dense_feature = tf.sparse_to_dense(tf.sparse_tensor_to_dense(index),
                                           [num_features],
                                           tf.sparse_tensor_to_dense(value))
        test_y = tf.cast(label, tf.float32)
        # test_x = tf.reshape(dense_feature, shape=[num_features, 1])
        test_x = dense_feature

        predict_confidence = tf.reduce_sum(tf.mul(w, test_x))
        predict_y = tf.sign(predict_confidence)
        cnt = tf.equal(test_y, predict_y)
        norm = tf.reduce_sum(tf.mul(w, w))

    with tf.Session("grpc://vm-22-%d:2222" % (FLAGS.task_index+1)) as sess:
        # only one client initializes the variable
        if FLAGS.task_index == 0:
            sess.run(tf.initialize_all_variables())
        coord = tf.train.Coordinator()
        threads = tf.train.start_queue_runners(sess=sess, coord=coord)
        for i in range(1, 1+iterate_num):
            # print 'iteration {}/{}'.format(i, iterate_num)
            output = sess.run(ggg)

            if i % break_point == 0:
                print 'reach break point'
                current_error = 0
                # out = open('error_asyn.csv', 'a')
                for j in range(test_num):
                    output2 = sess.run([test_y, predict_y, cnt, norm])
                    is_right = output2[2][0]
                    if not is_right:
                        current_error += 1
                    # print 'test_y:  ', output2[0],
                    # print '\tpredict_y:  ', output2[1],
                    # print '\t:', current_error,
                    # print '\t norm: ', output2[3]
                # print >> out, current_error
                print 'current error:  ', current_error
                # out.close()