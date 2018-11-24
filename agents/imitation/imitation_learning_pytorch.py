
import os
import scipy

import torch
import numpy as np

from carla.agent import Agent
from carla.carla_server_pb2 import Control
from carla_net import CarlaNet


class ImitationLearning(Agent):

    def __init__(self, city_name, avoid_stopping,
                 memory_fraction=0.25, image_cut=[115, 510]):

        Agent.__init__(self)

        self._image_size = (88, 200, 3)
        self._avoid_stopping = avoid_stopping

        dir_path = os.path.dirname(__file__)

        self._models_path = dir_path + '/model/'

        # tf.reset_default_graph()
        # self._sess.run(tf.global_variables_initializer())
        self.model = CarlaNet()
        self.model.eval()
        self.load_model()

        self._image_cut = image_cut

    def load_model(self, path_):

        if not os.path.exists(path_):
            raise RuntimeError('failed to find the models path')

        checkpoint = torch.load(path_)
        self.model.load_state_dict(checkpoint['state_dict'])

    def run_step(self, measurements, sensor_data, directions, target):

        control = self._compute_action(
            sensor_data['CameraRGB'].data,
            measurements.player_measurements.forward_speed,
            directions)

        return control

    def _compute_action(self, rgb_image, speed, direction=None):

        rgb_image = rgb_image[self._image_cut[0]:self._image_cut[1], :]

        image_input = scipy.misc.imresize(rgb_image, [self._image_size[0],
                                                      self._image_size[1]])

        image_input = image_input.astype(np.float32)
        image_input = np.expand_dims(
            np.transpose(image_input, (1, 2, 0)),
            axis=0)

        image_input = np.multiply(image_input, 1.0 / 255.0)
        speed = np.array([[speed]]).astype(np.float32) / 25.0
        direction = int(direction-2)

        steer, acc, brake = self._control_function(image_input,
                                                   speed,
                                                   direction)

        # This a bit biased, but is to avoid fake breaking

        if brake < 0.1:
            brake = 0.0

        if acc > brake:
            brake = 0.0

        # We limit speed to 35 km/h to avoid
        if speed > 10.0 and brake == 0.0:
            acc = 0.0

        control = Control()
        control.steer = steer
        control.throttle = acc
        control.brake = brake

        control.hand_brake = 0
        control.reverse = 0

        return control

    def _control_function(self, image_input, speed, control_input):

        img_ts = torch.from_numpy(image_input).cuda()
        speed_ts = torch.from_numpy(speed).cuda()

        with torch.no_grad():
            branches, pred_speed = self.model(img_ts, speed_ts)

        pred_result = branches[
            3*control_input:3*(control_input+1)].cpu().numpy()

        predicted_steers = (pred_result[0][0])

        predicted_acc = (pred_result[0][1])

        predicted_brake = (pred_result[0][2])

        if self._avoid_stopping:
            predicted_speed = pred_speed.squeeze().item()
            real_speed = speed * 25.0

            real_predicted = predicted_speed * 25.0
            if real_speed < 2.0 and real_predicted > 3.0:

                predicted_acc = 1 * (5.6 / 25.0 - speed) + predicted_acc

                predicted_brake = 0.0

                predicted_acc = predicted_acc

        return predicted_steers, predicted_acc, predicted_brake
