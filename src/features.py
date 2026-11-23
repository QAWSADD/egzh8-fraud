COMPONENTS = [f"V{i}" for i in range(1, 29)]
FEATURES = [*COMPONENTS, "Amount"]
CSV_COLUMNS = ["Time", *FEATURES, "Class"]
