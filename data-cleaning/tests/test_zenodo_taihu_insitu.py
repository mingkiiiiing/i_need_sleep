from pipeline.sources.zenodo_taihu_insitu import API, RECORD_ID


def test_taihu_insitu_source_is_fixed_to_public_zenodo_record():
    assert RECORD_ID == "10434391"
    assert API == "https://zenodo.org/api/records/10434391"
