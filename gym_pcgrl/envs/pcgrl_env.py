from gym_pcgrl.envs.probs import PROBLEMS
from gym_pcgrl.envs.reps import REPRESENTATIONS

from gym_pcgrl.envs.reps.narrow_rep import NarrowRepresentation
from gym_pcgrl.envs.probs.binary_prob import BinaryProblem

from gym_pcgrl.envs.helper import get_int_prob, get_string_map
import numpy as np
import gym
from gym import spaces
import PIL


import random
"""
The PCGRL GYM Environment
"""
class PcgrlEnv(gym.Env):
    """
    The type of supported rendering
    """
    metadata = {'render.modes': ['human', 'rgb_array']}

    """
    Constructor for the interface.

    Parameters:
        prob (string): the current problem. This name has to be defined in PROBLEMS
        constant in gym_pcgrl.envs.probs.__init__.py file
        rep (string): the current representation. This name has to be defined in REPRESENTATIONS
        constant in gym_pcgrl.envs.reps.__init__.py
    """
    def __init__(self, prob="binary", rep="narrow", n_agents = 2):
        self._prob = PROBLEMS[prob](n_agents)
        self._rep = REPRESENTATIONS[rep](n_agents)
        self.n_agents = n_agents
        self.active_agent = 0
        self.negative_switch = False
        self.agent_order = [i for i in range(self.n_agents)]
        # self._prob = BinaryProblem()
        # self._rep = NarrowRepresentation()
        self._rep_stats = None
        self._iteration = 0
        self._changes = [0 for _ in range(n_agents)]
        self._steps = [0 for _ in range(n_agents)]
        self._max_changes = max(int(0.2 * self._prob._width * self._prob._height), 1)
        self._max_iterations = self._max_changes * self._prob._width * self._prob._height
        self._heatmap = np.zeros((self._prob._height, self._prob._width))
        self.rewards = [[],[]]
        self.infos = False
        self.step_length = [1 for _ in range(n_agents)]

        self.seed()
        self.viewer = None

        self.action_space = self._rep.get_action_space(self._prob._width, self._prob._height, self.get_num_tiles())
        # self.observation_space = self._rep.get_observation_space(self._prob._width, self._prob._height, self.get_num_tiles())
        self.observation_space = self._rep.get_observation_space(self.get_num_tiles(),self._prob._width, self._prob._height)
        self.observation_space.spaces['heatmap'] = spaces.Box(low=0, high=self._max_changes, dtype=np.uint8, shape=(self._prob._height, self._prob._width))

    """
    Seeding the used random variable to get the same result. If the seed is None,
    it will seed it with random start.

    Parameters:
        seed (int): the starting seed, if it is None a random seed number is used.

    Returns:
        int[]: An array of 1 element (the used seed)
    """
    def seed(self, seed=None):
        seed = self._rep.seed(seed)
        self._prob.seed(seed)
        return [seed]

    """
    Resets the environment to the start state

    Returns:
        Observation: the current starting observation have structure defined by
        the Observation Space
    """
    def reset(self):
        self._changes = [0 for _ in range(self.n_agents)]
        self._steps = [0 for _ in range(self.n_agents)]
        self._iteration = 0
        self._rep.reset(self._prob._width, self._prob._height, get_int_prob(self._prob._prob, self._prob.get_tile_types()))
        self._rep_stats = self._prob.get_stats(get_string_map(self._rep._map, self._prob.get_tile_types()))
        self._prob.reset(self._rep_stats)
        self._heatmap = np.zeros((self._prob._height, self._prob._width))
        self.rewards = [[],[]]
        random.shuffle(self.agent_order)

        observations = []
        for i in range(self.n_agents):
            observation = self._rep.get_observation(i)
            observation["heatmap"] = self._heatmap.copy()
            observations.append(observation)
        # print(observations)
        return observations

    """
    Get the border tile that can be used for padding

    Returns:
        int: the tile number that can be used for padding
    """
    def get_border_tile(self):
        return self._prob.get_tile_types().index(self._prob._border_tile)

    """
    Get the number of different type of tiles that are allowed in the observation

    Returns:
        int: the number of different tiles
    """
    def get_num_tiles(self):
        return len(self._prob.get_tile_types())

    """
    Adjust the used parameters by the problem or representation

    Parameters:
        change_percentage (float): a value between 0 and 1 that determine the
        percentage of tiles the algorithm is allowed to modify. Having small
        values encourage the agent to learn to react to the input screen.
        **kwargs (dict(string,any)): the defined parameters depend on the used
        representation and the used problem
    """
    def adjust_param(self, **kwargs):
        if 'negative_switch' in kwargs:
            self.negative_switch = kwargs['negative_switch']
        if 'change_percentage' in kwargs:
            percentage = min(1, max(0, kwargs.get('change_percentage')))
            self._max_changes = max(int(percentage * self._prob._width * self._prob._height), 1)
        self._max_iterations = self._max_changes * self._prob._width * self._prob._height
        self.step_length = kwargs.get('step_length',self.step_length)
        self._prob.adjust_param(**kwargs)
        self._rep.adjust_param(self._prob._width, self._prob._height, **kwargs)
        self.action_space = self._rep.get_action_space(self._prob._width, self._prob._height, self.get_num_tiles())
        self.observation_space = self._rep.get_observation_space(self._prob._width, self._prob._height, self.get_num_tiles())
        self.observation_space.spaces['heatmap'] = spaces.Box(low=0, high=self._max_changes, dtype=np.uint8, shape=(self._prob._height, self._prob._width))

    """
    Advance the environment using a specific action

    Parameters:
        action: an action that is used to advance the environment (same as action space)

    Returns:
        observation: the current observation after applying the action
        float: the reward that happened because of applying that action
        boolean: if the problem eneded (episode is over)
        dictionary: debug information that might be useful to understand what's happening
    """
    def step(self, actions):
        random.shuffle(self.agent_order)
        self._iteration += 1
        done = False
        observations, rewards, dones, infos, actives = [None for i in range(self.n_agents)], [0 for i in range(self.n_agents)], [0 for i in range(self.n_agents)], {}, [0 for i in range(self.n_agents)]
        for j in range(self.n_agents):
            i = self.agent_order[j]
            #save copy of the old stats to calculate the reward
            old_stats = self._rep_stats

            # update the current state to the new state based on the taken action
            if not done:
                if self.negative_switch:
                    if i != self.active_agent:
                        actives[i] = 0 
                        change = 0
                    else:
                        actives[i] = 1
                        change, x, y = self._rep.update(actions[i],i)
                else:
                    change, x, y = self._rep.update(actions[i],i)
            else:
                change = 0
            # print("update", change,x,y)
            if change > 0:
                self._changes[i] += change
                self._heatmap[y][x] += 1.0
                self._rep_stats = self._prob.get_stats(get_string_map(self._rep._map, self._prob.get_tile_types()))
            self._steps[i] += self.active_agent == i
            # print(self._changes)
            # calculate the values
            observation = self._rep.get_observation(i)
            observation["heatmap"] = self._heatmap.copy()
            reward = self._prob.get_reward(self._rep_stats, old_stats)
            done = self._prob.get_episode_over(self._rep_stats,old_stats) or np.sum(self._changes) >= self._max_changes or self._iteration >= self._max_iterations
            info = self._prob.get_debug_info(self._rep_stats,old_stats,i)

            observations[i] = observation
            rewards[i] = reward
            dones[i] = done
            self.rewards[i].append(reward)

            info["iterations"] = self._iteration
            info["changes"] = self._changes[i]
            info["steps"] = self._steps[i]
            info["max_iterations"] = self._max_iterations
            info["max_changes"] = self._max_changes

            if self.negative_switch:
                if reward < 0:
                    self.active_agent = (self.active_agent + 1) % self.n_agents
            #print(info)
            # print(self.rewards)


            for k,v in info.items():
                if k in infos:
                    infos[k][i] = v
                else:
                    infos[k] = [0,0]
                    infos[k][i] = v

        if done:
            # print(self.rewards)
            infos["reward"] = [sum(reward) for reward in self.rewards]
            # print([sum(rewards) for rewards in self.rewards])
            self.reset()
        # else:
        #     info = None
        #return the values
        return observations, rewards, dones, infos, actives

    """
    Render the current state of the environment

    Parameters:
        mode (string): the value has to be defined in render.modes in metadata

    Returns:
        img or boolean: img for rgb_array rendering and boolean for human rendering
    """
    def render(self, mode='human'):
        tile_size=16
        img = self._prob.render(get_string_map(self._rep._map, self._prob.get_tile_types()))
        img = self._rep.render(img, self._prob._tile_size, self._prob._border_size).convert("RGB")
        if mode == 'rgb_array':
            return img
        elif mode == 'human':
            from gym.envs.classic_control import rendering
            if self.viewer is None:
                self.viewer = rendering.SimpleImageViewer()
            if not hasattr(img, 'shape'):
                img = np.array(img)
            self.viewer.imshow(img)
            return self.viewer.isopen

    """
    Close the environment
    """
    def close(self):
        if self.viewer:
            self.viewer.close()
            self.viewer = None


