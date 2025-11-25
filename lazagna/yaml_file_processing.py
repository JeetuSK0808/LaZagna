import yaml
from itertools import product
import copy
from typing import Dict, List, Any
import random
import os
import re

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
LAZAGNA_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, ".."))

def generate_seed_mapping(num_seeds: int) -> List[Dict]:
    """Generate seed and run number mapping"""
    # Generate random seeds
    seeds = random.sample(range(1, 10000), num_seeds)
    
    # Create mapping
    return [
        {'seed': seed, 'run_num': run_num} 
        for run_num, seed in enumerate(seeds, 1)
    ]

def load_param_ranges(yaml_file: str) -> Dict:
    """Load parameter ranges from YAML file and optionally add seed mapping"""
    with open(yaml_file, 'r') as f:
        params = yaml.safe_load(f)
    
    # If num_seeds is specified, generate and add seed mapping
    if params['num_seeds'] is not None and params['random_seed']:
        if 'linked_params' not in params:
            params['linked_params'] = {}
        params['linked_params']['seed_mapping'] = generate_seed_mapping(params['num_seeds'])
    
    seed = 1
    if not params['random_seed']:
        if 'non_random_seed' in params:
            seed = int(params['non_random_seed'])

        params['linked_params']['seed_mapping'] = [{'seed': seed, "run_num": 1}]

    # remove num_seeds from params
    if 'num_seeds' in params:
        del params['num_seeds']

    if 'random_seed' in params:
        del params['random_seed']

    if 'non_random_seed' in params:
        del params['non_random_seed']

    if 'sb_pattern' in params:
        # Validate the pattern format
        for pattern in params['sb_pattern']:
            if not isinstance(pattern, list) or len(pattern) != 2:
                raise ValueError("Each sb_pattern entry must be a list of two lists")
            for sublist in pattern:
                if not isinstance(sublist, list) or len(sublist) != 4:
                    raise ValueError("Each sb_pattern sublist must contain exactly 4 integers")
                if not all(isinstance(x, int) for x in sublist):
                    raise ValueError("All sb_pattern values must be integers")

        # Create a list of dictionaries for the linked parameters
        sb_pattern_mapping = [
            {
                'sb_input_pattern': input_pattern,
                'sb_output_pattern': output_pattern
            }
            for input_pattern, output_pattern in params['sb_pattern']
        ]
        
        # Add to linked_params
        params['linked_params']['sb_pattern_mapping'] = sb_pattern_mapping
        
        # Remove the original sb_pattern
        del params['sb_pattern']

    if 'sb_location_pattern' in params:
        params['linked_params']['sb_location_pattern'] = []
        for location in params['sb_location_pattern']:
            if location == 'custom':
                params['linked_params']['sb_location_pattern'].extend([{'sb_location_pattern': location, 'sb_grid_csv_path': i.replace('{lazagna_root}', LAZAGNA_ROOT)} for i in params['sb_grid_csv_path']])
            else:
                params['linked_params']['sb_location_pattern'].append({'sb_location_pattern': location, 'sb_grid_csv_path': ''})
        
    del params['sb_location_pattern']
    del params['sb_grid_csv_path']

    return params

def is_multi_option(value: Any) -> bool:
    """Check if a parameter has multiple options to try"""
    if not isinstance(value, list):
        return False
    if len(value) == 0:
        return False
    if isinstance(value[0], dict):
        return False
    return True

def generate_param_combinations(param_ranges: Dict) -> List[Dict]:
    """Generate all possible parameter combinations"""
    # Get all linked parameter groups
    linked_params = param_ranges.get('linked_params', {})
    independent_params = {k: v for k, v in param_ranges.items() 
                         if k != 'linked_params'}

    # Convert linked parameter groups into lists of dictionaries
    linked_param_groups = []
    for param_group, mappings in linked_params.items():
        for item in mappings:
            for key, value in item.items():
                if key == 'arch_file':
                    item[key] = value.replace('{lazagna_root}', LAZAGNA_ROOT)
        linked_param_groups.append(mappings)

    # Generate combinations of linked parameter groups
    linked_combinations = list(product(*linked_param_groups))

    # Separate multi-value and single-value independent parameters
    multi_values = {k: v for k, v in independent_params.items() 
                   if is_multi_option(v)}
    single_values = {k: v for k, v in independent_params.items() 
                    if not is_multi_option(v)}

    # Generate combinations for independent multi-value parameters
    multi_keys = list(multi_values.keys())
    value_combinations = list(product(*[multi_values[k] for k in multi_keys]))

    # Generate all possible combinations
    all_combinations = []
    
    # If there are no multiple options, still create one combination
    if not value_combinations:
        value_combinations = [()]

    # Combine all parameters
    for linked_combo in linked_combinations:
        for values in value_combinations:
            # Start with single values
            params = copy.deepcopy(single_values)
            
            # Add multi-value parameters
            params.update(dict(zip(multi_keys, values)))
            
            # Add all linked parameters
            for group in linked_combo:
                params.update(group)

            all_combinations.append(params)

    return all_combinations

def combinations_contains_duplicates(combinations):
    def dict_to_tuple(d):
        """Convert a dictionary to a tuple of sorted items for comparison, handling lists"""

        def make_hashable(value):
            if isinstance(value, list):
                return tuple(value)
            if isinstance(value, dict):
                return tuple(sorted((k, make_hashable(v)) for k, v in value.items()))
            return value
        
        return tuple(sorted((k, make_hashable(v)) for k, v in d.items()))

    # Make sure there are no duplicates in combinations
    unique_combinations = {}
    for combo in combinations:
        combo_tuple = dict_to_tuple(combo)
        if combo_tuple in unique_combinations:
            print(f"Found duplicate combination:")
            print("Original:", unique_combinations[combo_tuple])
            print("Duplicate:", combo)
        else:
            unique_combinations[combo_tuple] = combo

    if len(unique_combinations) != len(combinations):
        print(f"Warning: Found {len(combinations) - len(unique_combinations)} duplicate combinations")
        return True
    else:
        return False

def print_combinations(combinations):
    # Print results
    print(f"Total combinations: {len(combinations)}")
    prev_combination = None
    for i, combo in enumerate(combinations, 1):
        print(f"\nCombination {i}:")
        for key, value in sorted(combo.items()):
            print(f"  {key}: {value}")
        
        # Print difference from previous combination
        if prev_combination:
            diff = {k: [prev_combination.get(k), v] for k, v in combo.items() if prev_combination.get(k) != v}
            print(f"  Difference from previous combination: {diff}")
        prev_combination = combo

# Example usage
def get_run_params_from_yaml(file_path, verbose=False):
    """
    Load parameters from a YAML file and generate all combinations.
    """

    # Load parameters with 5 random seeds
    params = load_param_ranges(file_path)
    
    expected_params = [
        'original_dir', 'width', 'height', 'width_2d', 'height_2d', 'channel_width', 'type_sb',
        'percent_connectivity', 'place_algorithm', 'is_verilog_benchmarks',
        'connection_type', 'arch_file', 'num_seeds',
        'additional_vpr_options', 'cur_loop_identifier', 
        'benchmarks_dir', 'vertical_connectivity',
        'sb_switch_name', 'sb_segment_name', 'sb_input_pattern',
        'sb_output_pattern', 'sb_location_pattern', 'sb_grid_csv_path',
        'vertical_delay_ratio', 'base_delay_switch', 'switch_interlayer_pairs',
        'update_arch_delay', 'linked_params', 'sb_pattern',
    ]

    #check there are no extra parameters
    for key in params.keys():
        if key not in expected_params:
            print(f"Warning: Unexpected parameter '{key}' found in the YAML file.")

    if 'benchmarks_dir' in params:
        params['benchmarks_dir'] = params['benchmarks_dir'].replace('{lazagna_root}', LAZAGNA_ROOT)

    # Generate all combinations
    combinations = generate_param_combinations(params)
    
    # if verbose:
    #     print_combinations(combinations)

    if combinations_contains_duplicates(combinations):
        if verbose:
            print("Warning: Duplicate combinations found!")

    # Clean up combinates under teh following options:
    # if type_sb is "2d" or "3d_cb" or "3d_cb_out_only" and conneciton_type is not "subset" remove the combination
    # if type is "2d" and place_algorithm is not "cube_bb" remove the combination
    # if the type_sb is "2d" or "3d_cb" or "3d_cb_out_only" and percent_connectivity is not 1.0 remove the combination
    cleaned_combinations = []
    for combo in combinations:
        if combo['type_sb'] in ["2d", "3d_cb", "3d_cb_out_only"] and combo['connection_type'] != "subset":
            continue
        # if combo['type_sb'] == "2d" and (combo['place_algorithm'] != "cube_bb" or combo['vertical_delay_ratio'] != 1.0):
        if combo['type_sb'] == "2d" and (combo['place_algorithm'] != "cube_bb"):
            continue
        if combo['type_sb'] in ["2d", "3d_cb", "3d_cb_out_only"] and combo['percent_connectivity'] != 1.0:
            continue
        if combo['type_sb'] == '2d':
            combo['height'] = combo['height_2d']
            combo['width'] = combo['width_2d']

        del combo['width_2d']
        del combo['height_2d']

        combo['cur_loop_identifier'] = combo['cur_loop_identifier'] + "_vp_" + str(combo['vertical_delay_ratio'])

        cleaned_combinations.append(combo)

    
    if verbose:
        print(f"\nNumber of combinations: {len(cleaned_combinations)}")
        print_combinations(cleaned_combinations)   

    return cleaned_combinations

if __name__ == "__main__":
    # # Example usage
    yaml_file = "/home/memzfs_projects/vtr3d/LaZagna/setup_files/quick_test.yaml"
    combinations = get_run_params_from_yaml(yaml_file, verbose=True)
    print(f"Generated {len(combinations)} parameter combinations.")
    print("script dir: ", SCRIPT_DIR)
    print("lazagna root: ", LAZAGNA_ROOT)
