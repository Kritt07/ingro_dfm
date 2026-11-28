from norm_importer.grid_mapper import map_raw_grid_to_table_grid


def test_grouped_axis_retains_category_and_both_interval_bounds():
    raw = [["Ширина B, мм", "Открытый паз", "Открытый паз", "Закрытый паз", "Закрытый паз"],
           ["Ширина B, мм", "L ≤ 20 мм", "20 < L ≤ 40 мм", "L ≤ 20 мм", "20 < L ≤ 40 мм"],
           ["3", "0,22", "0,37", "0,31", "0,49"]]
    grid, warnings = map_raw_grid_to_table_grid(raw)
    assert grid.cols_range == ["Открытый паз | L ≤ 20 мм", "Открытый паз | 20 < L ≤ 40 мм",
                               "Закрытый паз | L ≤ 20 мм", "Закрытый паз | 20 < L ≤ 40 мм"]
    assert grid.row_param_name == "width_b_mm"
    assert grid.col_param_name == "length_l_mm"
    assert grid.values_matrix == [[.22, .37, .31, .49]]
    assert warnings


def test_interval_header_does_not_collapse_to_lower_bound():
    grid, warnings = map_raw_grid_to_table_grid([
        ["D", "L ≤ 20", "20 < L ≤ 40"], ["3", "1", "2"]])
    assert grid.cols_range == ["L ≤ 20", "20 < L ≤ 40"]
    assert warnings


def test_distinct_groups_with_unique_leaves_and_unlabelled_data_column():
    grid, warnings = map_raw_grid_to_table_grid([
        ["D", "Group A", "Group B", ""],
        ["D", "10", "20", ""],
        ["3", "1", "2", "3"],
        [None, "4", "5", "6"],
    ])
    assert grid.cols_range[:2] == ["Group A | 10", "Group B | 20"]
    assert len(grid.cols_range) == 3
    assert len(grid.rows_range) == 2
    assert grid.values_matrix == [[1., 2., 3.], [4., 5., 6.]]
    assert warnings
