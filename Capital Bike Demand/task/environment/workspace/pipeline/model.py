from sklearn.dummy import DummyRegressor


def build_model(seed: int):
    del seed
    return DummyRegressor(strategy="mean")
