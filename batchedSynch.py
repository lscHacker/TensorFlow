import tensorflow as tf
import os

worker_num = 5
num_features = 33762578
iterate_num = 500
test_num = 1000
break_point = 50

batch_size = 100

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
    with tf.device("/job:worker/task:0"):
        w = tf.Variable(tf.random_normal([num_features]), name="model")

    def read_my_file_format(filename_queue):
        reader = tf.TFRecordReader()
        _, serialized_example = reader.read(filename_queue)
        return serialized_example

    # 1. update indice to parameter server
    value_list = [0, 0, 0, 0, 0]
    index_list = [0, 0, 0, 0, 0]
    label_list = [0, 0, 0, 0, 0]
    for i in range(worker_num):
        with tf.device("/job:worker/task:%d" % i):
            filename_queue = tf.train.string_input_producer(input_producers[i], num_epochs=None, shuffle=False)
            serialized_example = read_my_file_format(filename_queue)
            min_after_dequeue = 10000
            capacity = min_after_dequeue + 10 * batch_size
            serialized_example_batch = tf.train.shuffle_batch(
                [serialized_example], batch_size=batch_size, capacity=capacity,
                min_after_dequeue=min_after_dequeue)
            features = tf.parse_example(serialized_example_batch,
                                        features={
                                            'label': tf.FixedLenFeature([1], dtype=tf.int64),
                                            'index': tf.VarLenFeature(dtype=tf.int64),
                                            'value': tf.VarLenFeature(dtype=tf.float32),
                                        })
            label = features['label']
            index = features['index']
            value = features['value']
            label_list[i] = label
            index_list[i] = index
            value_list[i] = value

    # 2. push dense weights to all workers
    weight_list = [0, 0, 0, 0, 0]
    with tf.device("/job:worker/task:0"):
        for i in range(worker_num):
            index = index_list[i]
            weight_list[i] = tf.gather(w, index.values)

    # 3. calculate gradients
    gradients = [0, 0, 0, 0, 0]
    ooo = []
    for i in range(worker_num):
        with tf.device("/job:worker/task:%d" % i):
            weight = weight_list[i]
            value = value_list[i]

            y = tf.cast(label_list[i], tf.float32)[0]
            x = value.values
            a = tf.mul(weight, x)
            b = tf.reduce_sum(a)
            c = tf.sigmoid(tf.mul(y, b))
            d = tf.mul(y, c-1)
            ooo.append(d)
            local_gradient = tf.mul(d, x)
            gradients[i] = tf.mul(local_gradient, 0.1)

    # 4. update gradients
    with tf.device("/job:worker/task:0"):
        aaa = gradients
        bbb = index_list
        ccc = ooo

        print 'gradient  ', gradients[0]
        print 'index   ', index_list[0].values

        w = tf.scatter_sub(w, index_list[0].values, gradients[0])
        w = tf.scatter_sub(w, index_list[1].values, gradients[1])
        w = tf.scatter_sub(w, index_list[2].values, gradients[2])
        w = tf.scatter_sub(w, index_list[3].values, gradients[3])
        w = tf.scatter_sub(w, index_list[4].values, gradients[4])

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
        test_x = dense_feature

        predict_confidence = tf.reduce_sum(tf.mul(w, test_x))
        predict_y = tf.sign(predict_confidence)
        cnt = tf.equal(test_y, predict_y)
        norm = tf.reduce_sum(tf.mul(w, w))

    with tf.Session("grpc://vm-22-1:2222") as sess:
        sess.run(tf.initialize_all_variables())
        coord = tf.train.Coordinator()
        threads = tf.train.start_queue_runners(sess=sess, coord=coord)
        for i in range(1, 1+iterate_num):

            print 'iteration {}/{}'.format(i, iterate_num)
            if i % 20 == 0:
                print 'iteration {}/{}'.format(i, iterate_num)
            output = sess.run([aaa, bbb, ccc])

            if i % break_point == 0:
                current_error = 0
                out = open('error_syn.csv', 'a')
                for _ in range(test_num):
                    output2 = sess.run([test_y, predict_y, cnt, norm])
                    is_right = output2[2][0]
                    if not is_right:
                        current_error += 1
                print 'error: ', current_error
                out.close()
        sess.close()