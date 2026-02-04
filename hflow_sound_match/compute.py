import numpy as np


# Compute Module
def get_index_of_closest_heart_rate(heart_rate, heart_rates):
    hrs = np.array(heart_rates, dtype=np.int32)
    distances = heart_rate - hrs
    # distances_abs = np.abs(distances)
    min_distance = min(np.abs(distances))
    if -min_distance in distances:
        min_distance = -min_distance
    (inds, ) = np.where(distances == min_distance)
    inds = inds.tolist()
    return inds
