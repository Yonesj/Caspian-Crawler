from core.normalization import LocationIndex


def test_a_source_place_id_resolves_through_reference_data(index):
    match = index.resolve(place_refs=['22'], source='divar')

    assert match.level == 'city'
    assert match.matched == 'source'
    assert (match.province_id, match.city_id, match.region_id) == (1, 22, None)


def test_the_most_specific_source_ref_wins_and_fills_its_ancestors(index):
    # Sheypoor publishes the neighbourhood first, then the city and province.
    match = index.resolve(
        place_refs=['band-e-pey', 'nowshahr', 'mazandaran'], source='sheypoor'
    )

    assert match.level == 'region'
    assert (match.province_id, match.city_id, match.region_id) == (1, 23, 31)


def test_free_text_falls_back_to_the_most_specific_fragment(index):
    match = index.resolve(raw_location='مازندران، نوشهر، بندپی')

    assert match.level == 'region'
    assert match.matched == 'text'
    assert (match.province_id, match.city_id, match.region_id) == (1, 23, 31)


def test_aliases_match_through_unfolded_spellings(index):
    assert index.resolve(raw_location='بندر انزلى').city_id == 24
    assert index.resolve(raw_location='ساری').city_id == 22


def test_text_can_refine_a_coarser_source_ref(index):
    # Divar gives us the city; the printed text names the neighbourhood.
    match = index.resolve(raw_location='بندپی', place_refs=['nowshahr'], source='sheypoor')

    assert match.level == 'region'
    assert match.region_id == 31


def test_an_unknown_place_leaves_every_level_empty(index):
    match = index.resolve(raw_location='تبریز، ولیعصر')

    assert not match.resolved
    assert (match.province_id, match.city_id, match.region_id) == (None, None, None)
    assert match.text == 'تبریز، ولیعصر'


def test_resolving_nothing_is_allowed(index):
    match = index.resolve()

    assert not match.resolved
    assert match.text is None


def test_aliases_pointing_at_unknown_rows_are_ignored():
    index = LocationIndex(
        provinces=[{'id': 1, 'name_fa': 'مازندران'}],
        aliases=[{'alias': 'جایی', 'level': 'city', 'id': 999}],
    )

    assert not index.resolve(raw_location='جایی').resolved


def test_inactive_levels_are_absent_from_the_index():
    # Built from rows already filtered by is_active, an unknown level simply
    # has nothing to match; the index never invents an ancestor.
    index = LocationIndex(cities=[{'id': 22, 'name_fa': 'ساری', 'province_id': None}])

    match = index.resolve(raw_location='ساری')

    assert match.city_id == 22
    assert match.province_id is None
