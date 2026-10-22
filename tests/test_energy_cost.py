import pytest

from agri_twin.application.energy_cost import Tariff, TariffError, energy_cost
from agri_twin.interfaces.frontend_api import InteractiveFrontendAdapter

TIMES = [f"2027-01-01T{h:02d}:00:00+00:00" for h in range(24)] + ["2028-01-01T00:00:00+00:00"]
ONE_KWH = [1.0] * 25


def test_a_single_price_multiplies_the_energy():
    result = energy_cost(TIMES, ONE_KWH, {"flat_per_kwh": 0.2})
    assert result["total_cost"] == pytest.approx(5.0)
    assert result["cost_cumulative"][2] == pytest.approx(0.6)
    assert result["currency"] == "EUR"


def test_nothing_is_assumed_without_a_price():
    result = energy_cost(TIMES, ONE_KWH, {})
    assert result["total_cost"] is None and result["cost"][0] is None and result["steps_priced"] == 0


def test_a_yearly_table_overrides_the_flat_price_and_falls_back_to_it():
    result = energy_cost(TIMES, ONE_KWH, {"flat_per_kwh": 0.1, "yearly": {"2027": 0.3}})
    assert result["price_per_kwh"][0] == 0.3 and result["price_per_kwh"][-1] == 0.1
    no_fallback = energy_cost(TIMES, ONE_KWH, {"yearly": {"2027": 0.3}})
    assert no_fallback["price_per_kwh"][-1] is None and no_fallback["cost"][-1] is None and no_fallback["total_cost"] is None
    assert no_fallback["cost_cumulative"][23] == pytest.approx(7.2)


def test_time_of_day_bands_with_absolute_prices_factors_and_midnight_wrap():
    tariff = {"flat_per_kwh": 0.2, "time_of_day": [{"from_hour": 22, "to_hour": 6, "price_per_kwh": 0.05}, {"from_hour": 18, "to_hour": 22, "factor": 2.0}]}
    prices = energy_cost(TIMES, ONE_KWH, tariff)["price_per_kwh"]
    assert prices[23] == prices[0] == prices[5] == 0.05
    assert prices[6] == prices[17] == 0.2
    assert prices[18] == prices[21] == pytest.approx(0.4)


def test_bands_follow_the_utc_offset():
    tariff = {"time_of_day": [{"from_hour": 0, "to_hour": 8, "price_per_kwh": 0.05}], "flat_per_kwh": 0.2, "utc_offset_hours": 1}
    prices = energy_cost(TIMES, ONE_KWH, tariff)["price_per_kwh"]
    assert prices[6] == 0.05 and prices[7] == 0.2


def test_a_step_whose_energy_is_not_estimable_has_no_cost_and_stops_the_running_sum():
    result = energy_cost(TIMES[:4], [1.0, None, 1.0, 1.0], {"flat_per_kwh": 1.0})
    assert result["cost"] == [1.0, None, 1.0, 1.0] and result["cost_cumulative"] == [1.0, None, None, None]


@pytest.mark.parametrize("tariff", [{"flat_per_kwh": -1}, {"flat_per_kwh": True}, {"price": 1}, {"yearly": {"x": 1}}, {"yearly": {"2027": -0.1}},
                                    {"time_of_day": [{"from_hour": 0, "to_hour": 5}]}, {"time_of_day": [{"from_hour": 0, "to_hour": 5, "price_per_kwh": 1, "factor": 1}]},
                                    {"time_of_day": [{"from_hour": 0, "to_hour": 8, "factor": 1}, {"from_hour": 6, "to_hour": 10, "factor": 1}]},
                                    {"time_of_day": [{"from_hour": 3, "to_hour": 3, "factor": 1}]}, {"utc_offset_hours": 20}])
def test_invalid_tariffs_are_rejected(tariff):
    with pytest.raises(TariffError):
        Tariff.from_mapping(tariff)


def test_the_series_must_be_coherent():
    with pytest.raises(TariffError):
        energy_cost(TIMES, [1.0], {"flat_per_kwh": 1})
    with pytest.raises(TariffError):
        energy_cost(["nope"], [1.0], {"flat_per_kwh": 1})


def test_the_api_route_is_pure_and_validates_its_body():
    adapter = InteractiveFrontendAdapter()
    body = {"tariff": {"flat_per_kwh": 0.5}, "time": TIMES[:2], "energy_kwh": [2.0, 2.0]}
    assert adapter.energy_cost(body)["total_cost"] == pytest.approx(2.0) and adapter.energy_cost(body) == adapter.energy_cost(body)
    with pytest.raises(ValueError):
        adapter.energy_cost({"tariff": {}})
