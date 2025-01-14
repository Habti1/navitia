# Copyright (c) 2001-2022, Hove and/or its affiliates. All rights reserved.
#
# This file is part of Navitia,
#     the software to build cool stuff with public transport.
#
# Hope you'll enjoy and contribute to this project,
#     powered by Hove (www.hove.com).
# Help us simplify mobility and open public transport:
#     a non ending quest to the responsive locomotion way of traveling!
#
# LICENCE: This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program. If not, see <http://www.gnu.org/licenses/>.
#
# Stay tuned using
# twitter @navitia
# channel `#navitia` on riot https://riot.im/app/#/room/#navitia:matrix.org
# https://groups.google.com/d/forum/navitia
# www.navitia.io

import logging
import json
from collections import namedtuple
from jormungandr.utils import get_olympic_site, local_str_date_to_utc, date_to_timestamp, str_to_dt
import boto3
from jormungandr import app
from botocore.client import Config


AttractivityVirtualFallback = namedtuple("AttractivityVirtualFallback", "attractivity, virtual_duration")


class OlympicSiteParamsManager:
    def __init__(self, instance):
        self.olympic_site_params = dict()
        self.instance = instance

    def build_olympic_site_params(self, scenario, data):
        if not scenario:
            logging.getLogger(__name__).warning("Impossible to build olympic_site_params: Empty scenario")
            return {}
        return {
            spt_id: AttractivityVirtualFallback(d["attractivity"], d["virtual_fallback"])
            for spt_id, d in data.get("scenarios", {}).get(scenario, {}).get("stop_points", {}).items()
        }

    def get_valid_scenario_name(self, scenario_list, key, datetime):
        for event in scenario_list:
            if event["from_timestamp"] <= datetime <= event["to_timestamp"]:
                return event.get(key)
        return None

    def get_dict_scenario(self, poi_uri, key, datetime):
        data = self.olympic_site_params.get(poi_uri)
        if not data:
            return {}
        scenario_name = self.get_valid_scenario_name(data.get("events", []), key, datetime)
        if scenario_name:
            return self.build_olympic_site_params(scenario_name, data)
        return {}

    def get_dict_additional_parameters(self, poi_uri, key, datetime):
        data = self.olympic_site_params.get(poi_uri)
        if not data:
            return {}
        scenario_name = self.get_valid_scenario_name(data.get("events", []), key, datetime)
        if scenario_name:
            return data.get("scenarios", {}).get(scenario_name, {}).get("additional_parameters", {})
        return {}

    def get_strict_parameter(self, poi_uri):
        data = self.olympic_site_params.get(poi_uri)
        if not data:
            return False
        return data.get("strict", False)

    def get_timestamp(self, str_datetime):
        if self.instance.timezone:
            dt = local_str_date_to_utc(str_datetime, self.instance.timezone)
        else:
            dt = str_to_dt(str_datetime)
        return date_to_timestamp(dt) if dt else None

    def str_datetime_time_stamp(self, json_data):
        """
        transform from_datetime, to_datetime to time_stamp
        """
        for key, value in json_data.items():
            for event in value.get("events", []):
                str_from_datetime = event.get("from_datetime")
                str_to_datetime = event.get("to_datetime")
                if str_from_datetime and str_to_datetime:
                    event["from_timestamp"] = self.get_timestamp(str_from_datetime)
                    event["to_timestamp"] = self.get_timestamp(str_to_datetime)

    def get_json_content(self, s3_object):
        logger = logging.getLogger(__name__)
        try:
            file_content = s3_object.get()['Body'].read().decode('utf-8')
            return json.loads(file_content)
        except Exception:
            logger.exception('Error while loading file: {}'.format(s3_object.key))
            return {}

    def fill_olympic_site_params_from_s3(self):
        logger = logging.getLogger(__name__)
        bucket_params = app.config.get('OLYMPIC_SITE_PARAMS_BUCKET', {})
        if not bucket_params:
            logger.debug("Reading stop points attractivities, undefined bucket_params")
            return
        bucket_name = bucket_params.get("name")
        if not bucket_name:
            logger.debug("Reading stop points attractivities, undefined bucket_name")
            return

        args = bucket_params.get(
            "args", {"connect_timeout": 2, "read_timeout": 2, "retries": {'max_attempts': 0}}
        )
        s3_resource = boto3.resource('s3', config=Config(**args))

        folder = app.config.get('OLYMPIC_SITE_PARAMS_BUCKET', {}).get("folder", "olympic_site_params")
        try:
            my_bucket = s3_resource.Bucket(bucket_name)
            for obj in my_bucket.objects.filter(Prefix="{}/{}/".format(folder, self.instance.name)):
                if obj.key.endswith('.json'):
                    json_content = self.get_json_content(obj)
                    self.str_datetime_time_stamp(json_content)
                    self.olympic_site_params.update(json_content)
        except Exception:
            logger.exception("Error on OlympicSiteParamsManager")

    def build(self, pt_object_origin, pt_object_destination, api_request):
        # Warning, the order of functions is important
        # Order 1 : get_olympic_site_params
        # Order 2 : build_api_request
        api_request["olympic_site_params"] = self.get_olympic_site_params(
            pt_object_origin, pt_object_destination, api_request
        )

        self.build_api_request(api_request)

    def manage_forbidden_uris(self, api_request, forbidden_uris):
        if not forbidden_uris:
            return
        if api_request.get("forbidden_uris[]"):
            api_request["forbidden_uris[]"] += forbidden_uris
        else:
            api_request["forbidden_uris[]"] = forbidden_uris

    def build_api_request(self, api_request):
        olympic_site_params = api_request.get("olympic_site_params")
        if not olympic_site_params:
            return

        # Add keep_olympics_journeys parameter
        if api_request.get("_keep_olympics_journeys") is None and olympic_site_params:
            api_request["_keep_olympics_journeys"] = True

        # Add additional parameters
        for key, value in olympic_site_params.get("additional_parameters", {}).items():
            if key == "forbidden_uris":
                self.manage_forbidden_uris(api_request, value)
            else:
                api_request[key] = value

        # Add forbidden_uri
        self.manage_forbidden_uris(
            api_request, self.instance.olympics_forbidden_uris.pt_object_olympics_forbidden_uris
        )

        # Add criteria
        if api_request.get("criteria") in ["departure_stop_attractivity", "arrival_stop_attractivity"]:
            return
        if olympic_site_params.get("departure_scenario"):
            api_request["criteria"] = "departure_stop_attractivity"
        elif olympic_site_params.get("arrival_scenario"):
            api_request["criteria"] = "arrival_stop_attractivity"

    def get_olympic_site_params(self, pt_origin_detail, pt_destination_detail, api_request):

        origin_olympic_site = get_olympic_site(pt_origin_detail, self.instance)
        destination_olympic_site = get_olympic_site(pt_destination_detail, self.instance)

        if not origin_olympic_site and not destination_olympic_site:
            return {}

        if origin_olympic_site and destination_olympic_site:
            origin_olympic_site = None

        attractivities = dict()
        virtual_duration = dict()
        attractivities.update(api_request.get('_olympics_sites_attractivities[]') or [])
        virtual_duration.update(api_request.get('_olympics_sites_virtual_fallback[]') or [])
        if attractivities:
            result = dict()
            for spt_id, attractivity in attractivities.items():
                virtual_fallback = virtual_duration.get(spt_id, 0)
                result[spt_id] = AttractivityVirtualFallback(attractivity, virtual_fallback)
            if origin_olympic_site:
                return {"departure_scenario": result}
            return {"arrival_scenario": result}

        if not self.olympic_site_params:
            return {}

        departure_olympic_site_params = (
            self.get_dict_scenario(origin_olympic_site.uri, "departure_scenario", api_request["datetime"])
            if origin_olympic_site
            else {}
        )
        arrival_olympic_site_params = (
            self.get_dict_scenario(destination_olympic_site.uri, "arrival_scenario", api_request["datetime"])
            if destination_olympic_site
            else {}
        )

        if departure_olympic_site_params:
            return {
                "departure_scenario": departure_olympic_site_params,
                "additional_parameters": self.get_dict_additional_parameters(
                    origin_olympic_site.uri, "departure_scenario", api_request["datetime"]
                ),
                "strict": self.get_strict_parameter(origin_olympic_site.uri) if origin_olympic_site else False,
            }
        if arrival_olympic_site_params:
            return {
                "arrival_scenario": arrival_olympic_site_params,
                "additional_parameters": self.get_dict_additional_parameters(
                    destination_olympic_site.uri, "arrival_scenario", api_request["datetime"]
                ),
                "strict": self.get_strict_parameter(destination_olympic_site.uri)
                if destination_olympic_site
                else False,
            }
        return {}
