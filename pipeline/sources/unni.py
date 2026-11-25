from pipeline.sources.base import SourceAdapter, SourcePolicy


class UnniAdapter(SourceAdapter):
    policy = SourcePolicy("unni", "unni.app", "", 5)

    def parse_detail(self, html: str, url: str):
        raise NotImplementedError("unni.app collection disabled; requires future authorization")
