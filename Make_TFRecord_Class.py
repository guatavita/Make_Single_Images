__author__ = 'Brian M Anderson'
# Created on 4/7/2020

import tensorflow as tf
import SimpleITK as sitk
import numpy as np
import os, pickle
from .Plot_And_Scroll_Images.Plot_Scroll_Images import plot_scroll_Image
from _collections import OrderedDict
from threading import Thread
from multiprocessing import cpu_count
from queue import *


def save_obj(path, obj): # Save almost anything.. dictionary, list, etc.
    if path.find('.pkl') == -1:
        path += '.pkl'
    with open(path, 'wb') as f:
        pickle.dump(obj, f)
    return None


def load_obj(path):
    if path.find('.pkl') == -1:
        path += '.pkl'
    if os.path.exists(path):
        with open(path, 'rb') as f:
            return pickle.load(f)
    else:
        out = {}
        return out


def _bytes_feature(value):
    if isinstance(value, type(tf.constant(0))):
        value = value.numpy()
    return tf.train.Feature(bytes_list=tf.train.BytesList(value=[value]))


def _float_feature(value):
    return tf.train.Feature(float_list=tf.train.FloatList(value=[value]))


def _float_features(values):
    return tf.train.Features(float_list=tf.train.FloatList(values=[values]))


def _int64_feature(value):
    return tf.train.Feature(int64_list=tf.train.Int64List(value=[value]))


def return_example_proto(base_dictionary):
    feature = {}
    for key in base_dictionary:
        data = base_dictionary[key]
        if type(data) is int:
            feature[key] = _int64_feature(data)
        elif type(data) is np.ndarray:
            feature[key] = _bytes_feature(data.tostring())
    example_proto = tf.train.Example(features=tf.train.Features(feature=feature))
    return example_proto


def serialize_example(image_path, annotation_path, overall_dict={}, wanted_values_for_bboxes=None, extension=np.inf,
                      is_3D=True):
    base_dictionary = get_features(image_path,annotation_path,extension=extension,
                                   wanted_values_for_bboxes=wanted_values_for_bboxes, is_3D=is_3D)
    if is_3D:
        example_proto = return_example_proto(base_dictionary)
        overall_dict[image_path] = example_proto.SerializeToString()
    else:
        for image_key in base_dictionary:
            example_proto = return_example_proto(base_dictionary[image_key])
            overall_dict['{}_{}'.format(image_path,image_key)] = example_proto.SerializeToString()


def get_bounding_boxes(annotation_handle,value):
    Connected_Component_Filter = sitk.ConnectedComponentImageFilter()
    stats = sitk.LabelShapeStatisticsImageFilter()
    thresholded_image = sitk.BinaryThreshold(annotation_handle,lowerThreshold=value,upperThreshold=value+1)
    connected_image = Connected_Component_Filter.Execute(thresholded_image)
    stats.Execute(connected_image)
    bounding_boxes = np.asarray([stats.GetBoundingBox(l) for l in stats.GetLabels()]).astype('int32')
    volumes = np.asarray([stats.GetPhysicalSize(l) for l in stats.GetLabels()]).astype('float32')
    return bounding_boxes, volumes


def return_image_feature_description(wanted_values_for_bboxes=None, is_3D=True):
    if is_3D:
        image_feature_description = {
            'image': tf.io.FixedLenFeature([], tf.string),
            'annotation': tf.io.FixedLenFeature([], tf.string),
            'start': tf.io.FixedLenFeature([], tf.int64),
            'stop': tf.io.FixedLenFeature([], tf.int64),
            'z_images': tf.io.FixedLenFeature([], tf.int64),
            'rows': tf.io.FixedLenFeature([], tf.int64),
            'cols': tf.io.FixedLenFeature([], tf.int64),
            'spacing': tf.io.FixedLenFeature([], tf.string)
        }
        if wanted_values_for_bboxes is not None:
            for val in wanted_values_for_bboxes:
                image_feature_description['bounding_boxes_{}'.format(val)] = tf.io.FixedLenFeature([], tf.string)
                image_feature_description['volumes_{}'.format(val)] = tf.io.FixedLenFeature([], tf.string)
    else:
        image_feature_description = {
            'image': tf.io.FixedLenFeature([], tf.string),
            'annotation': tf.io.FixedLenFeature([], tf.string),
            'rows': tf.io.FixedLenFeature([], tf.int64),
            'cols': tf.io.FixedLenFeature([], tf.int64)
        }
    return image_feature_description


def get_features(image_path, annotation_path, extension=np.inf, wanted_values_for_bboxes=None,
                 is_3D=True):
    image_handle, annotation_handle = sitk.ReadImage(image_path), sitk.ReadImage(annotation_path)
    features = OrderedDict()
    annotation = sitk.GetArrayFromImage(annotation_handle).astype('int8')
    non_zero_values = np.where(annotation > 0)[0]
    if not np.any(non_zero_values):
        print('Found nothing for ' + image_path)
    start = int(non_zero_values[0])
    stop = int(non_zero_values[-1])
    start_images = max([start - extension, 0])
    stop_images = min([stop + extension, annotation.shape[0]])
    image = sitk.GetArrayFromImage(image_handle).astype('float32')
    if start_images != 0 or stop_images != image.shape[0]:
        annotation = annotation[start_images:stop_images, ...]
        image = image[start_images:stop_images,...]
        annotation_handle = sitk.GetImageFromArray(annotation)
        non_zero_values = np.where(annotation > 0)[0]
        if not np.any(non_zero_values):
            print('Found nothing for ' + image_path)
        start = int(non_zero_values[0])
        stop = int(non_zero_values[-1])
    z_images, rows, cols = annotation.shape
    image, annotation = image.astype('float32'), annotation.astype('int8')
    if is_3D:
        features['image'] = image
        features['annotation'] = annotation
        features['start'] = start
        features['stop'] = stop
        features['z_images'] = z_images
        features['rows'] = rows
        features['cols'] = cols
        features['spacing'] = np.asarray(annotation_handle.GetSpacing())
        if wanted_values_for_bboxes is not None:
            for val in wanted_values_for_bboxes:
                slices = np.where(annotation == val)
                features['volumes_{}'.format(val)] = np.asarray([0])
                if slices:
                    bounding_boxes, volumes = get_bounding_boxes(annotation_handle,val)
                    features['bounding_boxes_{}'.format(val)] = bounding_boxes
                    features['volumes_{}'.format(val)] = volumes
    else:
        for index in range(z_images):
            image_features = OrderedDict()
            image_features['image'] = image[index]
            image_features['annotation'] = annotation[index]
            image_features['rows'] = rows
            image_features['cols'] = cols
            features['Image_{}'.format(index)] = image_features
    return features


def worker_def(A):
    q = A[0]
    base_class = serialize_example
    while True:
        item = q.get()
        if item is None:
            break
        else:
            try:
                base_class(**item)
            except:
                print('failed?')
            q.task_done()


def return_parse_function(image_feature_description):

    def _parse_image_function(example_proto):
        return tf.io.parse_single_example(example_proto, image_feature_description)
    return _parse_image_function


def read_dataset(filename, features):
    raw_dataset = tf.data.TFRecordDataset([filename], num_parallel_reads=tf.data.experimental.AUTOTUNE)
    parsed_image_dataset = raw_dataset.map(return_parse_function(features))


def write_tf_record(path, record_name='Record', rewrite=False, thread_count=int(cpu_count() * .9 - 1),
                    wanted_values_for_bboxes=None, extension=None, is_3D=True):
    add = '_2D'
    if is_3D:
        add = '_3D'
        if extension is None:
            extension = np.inf
    elif extension is None:
        extension = 0
    filename = os.path.join(path,'{}{}.tfrecord'.format(record_name,add))
    if os.path.exists(filename) and not rewrite:
        return None
    data_dict = {'Images':{}, 'Annotations':{}}
    image_files = [i for i in os.listdir(path) if i.find('Overall_Data') == 0]
    for file in image_files:
        iteration = file.split('_')[-1].split('.')[0]
        data_dict['Images'][iteration] = os.path.join(path,file)

    annotation_files = [i for i in os.listdir(path) if i.find('Overall_mask') == 0]
    for file in annotation_files:
        iteration = file.split('_y')[-1].split('.')[0]
        data_dict['Annotations'][iteration] = os.path.join(path,file)
    overall_dict = {}
    q = Queue(maxsize=thread_count)
    A = [q,]
    threads = []
    for worker in range(thread_count):
        t = Thread(target=worker_def, args=(A,))
        t.start()
        threads.append(t)
    for iteration in list(data_dict['Images'].keys()):
        print(iteration)
        image_path, annotation_path = data_dict['Images'][iteration], data_dict['Annotations'][iteration]
        item = {'image_path':image_path,'annotation_path':annotation_path,'overall_dict':overall_dict,
                'wanted_values_for_bboxes':wanted_values_for_bboxes, 'extension':extension, 'is_3D':is_3D}
        q.put(item)
    for i in range(thread_count):
        q.put(None)
    for t in threads:
        t.join()
    print('Writing record...')
    examples = 0
    writer = tf.io.TFRecordWriter(filename)
    for image_path in overall_dict.keys():
        writer.write(overall_dict[image_path])
        examples += 1
    writer.close()
    fid = open(filename.replace('.tfrecord','_Num_Examples.txt'),'w+')
    fid.write(str(examples))
    fid.close()
    features = return_image_feature_description(wanted_values_for_bboxes, is_3D=is_3D)
    save_obj(filename.replace('.tfrecord','_features.pkl'),features)
    print('Finished!')
    return None


if __name__ == '__main__':
    pass
