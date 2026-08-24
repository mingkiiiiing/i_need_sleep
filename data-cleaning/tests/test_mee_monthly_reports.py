from pipeline.sources.mee_monthly_reports import extract_taihu_section, parse_taihu_section


def test_extract_and_parse_taihu_section_without_inventing_concentrations():
    text = "三、湖泊和水库\n1 太湖\n1.1 湖体\n太湖湖体共监测17个点位。全湖整体为轻度污染，主要超标指标为总磷。总氮单独评价时：全湖整体为IV类水质。营养状态评价表明：全湖整体为轻度富营养。\n1.2 环湖河流\n内容\n2 巢湖"
    section = extract_taihu_section(text)
    result = parse_taihu_section(section)
    assert result["monitoring_point_count"] == 17
    assert result["whole_lake_status"] == "轻度污染"
    assert result["main_exceedance_indicators"] == "总磷"
    assert result["tp_concentration_mentions"] is None


def test_whole_lake_status_does_not_take_trophic_status():
    section = "1 太湖 1.1 湖体 太湖全湖整体水质良好。其中，东部沿岸区水质为优。营养状态评价表明：全湖整体为轻度富营养。1.2 环湖河流主要超标指标为溶解氧。"
    result = parse_taihu_section(section)
    assert result["whole_lake_status"] == "良好"
    assert result["main_exceedance_indicators"] is None
    assert result["trophic_assessment"] == "全湖整体为轻度富营养。"
