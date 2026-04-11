from urllib.parse import urlparse, parse_qs

url = "https://www.linkedin.com/jobs/search/?currentJobId=4371501817&distance=25&f_E=3%2C4&f_I=96&f_JT=F%2CC&f_PP=103100785&geoId=102890719&keywords=Project%20Manager&origin=JOB_SEARCH_PAGE_JOB_FILTER&refresh=true&sortBy=R&spellCorrectionEnabled=true"

params = parse_qs(urlparse(url).query)
codes = params.get("f_I", [""])[0].split(",")

print(codes)   # ['96', '4', '6']