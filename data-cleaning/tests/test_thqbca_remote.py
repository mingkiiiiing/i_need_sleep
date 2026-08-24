import json

from pipeline.sources.thqbca_remote import build_remote_product_index


def test_remote_product_index_preserves_real_members_without_fake_pixel_values(tmp_path):
    listing = tmp_path / "listing.json"
    listing.write_text(json.dumps({
        "members": [
            "THQBCA-V2/2.Bio-optics/2.2FAC/TH_FAC_2020.tif",
            "THQBCA-V2/2.Bio-optics/2.4Chla/TH_Chla_2019.tif",
            "THQBCA-V2/2.Bio-optics/2.1AquaticVegetation/TH_vege_2020-09-08.tif",
        ]
    }), encoding="utf-8")
    output = tmp_path / "remote.csv"
    manifest = tmp_path / "remote.json"
    result = build_remote_product_index(listing, output, manifest)
    assert result["records"] == 3
    assert result["value_status"] == "not_extracted"
    rows = output.read_text(encoding="utf-8-sig").splitlines()
    assert len(rows) == 4
    assert "remote_chlorophyll_a" in output.read_text(encoding="utf-8-sig")
