from sklearn.ensemble import HistGradientBoostingRegressor


def build_model(seed: int):
    return HistGradientBoostingRegressor(
        loss="poisson",
        learning_rate=0.06,
        max_iter=300,
        max_leaf_nodes=63,
        min_samples_leaf=20,
        l2_regularization=1.0,
        early_stopping=False,
        random_state=seed,
    )
