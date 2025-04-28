import json


def load_json_as_dict(file_path):
    """
    Loads json data from file_path
    :param file_path: path to load data from, should be a dictionary data element
    :return:
    """
    try:
        with open(file_path, 'r') as file:
            data = json.load(file)
            return data
    except FileNotFoundError:
        print(f"Error: File not found at '{file_path}'")
        return None
    except json.JSONDecodeError:
        print(f"Error: Invalid JSON format in '{file_path}'")
        return None


def save_dict_to_json(data, file_path):
    """
    Saves json data to file_path
    :param data: dictionary to add to the file_path
    :param file_path:  path to save data to
    :return:
    """
    with open(file_path, 'w') as file:
        json.dump(data, file, indent=4)

