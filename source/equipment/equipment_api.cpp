/* Copyright © 2001-2019, Canal TP and/or its affiliates. All rights reserved.

This file is part of Navitia,
    the software to build cool stuff with public transport.

Hope you'll enjoy and contribute to this project,
    powered by Canal TP (www.canaltp.fr).
Help us simplify mobility and open public transport:
    a non ending quest to the responsive locomotion way of traveling!

LICENCE: This program is free software; you can redistribute it and/or modify
it under the terms of the GNU Affero General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
GNU Affero General Public License for more details.

You should have received a copy of the GNU Affero General Public License
along with this program. If not, see <http://www.gnu.org/licenses/>.

Stay tuned using
twitter @navitia
IRC #navitia on freenode
https://groups.google.com/d/forum/navitia
www.navitia.io
*/

#include "equipment_api.h"
#include "utils/paginate.h"

#include "boost/range/algorithm.hpp"

#include <map>
#include <vector>
#include <string>

namespace navitia {
namespace equipment {

namespace {
    const std::string build_ptref_filter(const std::string& line_uri, const std::string& filter) {
        std::string sa_filter = "line.uri=" + line_uri;
        if(filter.size()) {
            sa_filter += " and (" + filter + ")";
        }
        return sa_filter;
    }

    void fill_equipment_to_pb(const equipment::StopAreasPerLine& sas_per_line,
                              PbCreator& pb_creator, int depth) {
        for(auto& line : sas_per_line) {
            auto report = pb_creator.add_equipment_reports();
            pb_creator.fill(line.first, report->mutable_line(), depth);
            for(auto& sa : line.second) {
                auto sa_equip = report->add_stop_area_equipments();
                pb_creator.fill(sa, sa_equip->mutable_stop_area(), depth);
            }
        }
    }
}

StopAreasPerLine get_stop_areas_per_line(const type::Data& data, const std::string& filter,
                                         const ForbiddenUris& forbidden_uris) {
    StopAreasPerLine res;
    type::Indexes line_indices = ptref::make_query(type::Type_e::Line, filter, forbidden_uris, data);
    auto lines = data.get_data<type::Line>(line_indices);
    for(const auto line : lines) {
        const std::string sa_filter = build_ptref_filter(line->uri, filter);
        const type::Indexes sa_indexes = ptref::make_query(type::Type_e::StopArea, sa_filter, forbidden_uris, data);
        res.emplace_back(line, data.get_data<type::StopArea>(sa_indexes));
    }

    return res;
}

void equipment_reports(PbCreator& pb_creator, const std::string& filter,
                       int count, int depth, int start_page,
                       const ForbiddenUris& forbidden_uris) {
    const type::Data& data = *pb_creator.data;
    try {
        const auto sas_per_line = get_stop_areas_per_line(data, filter, forbidden_uris);
        const auto paginated_sas = paginate(sas_per_line, count, start_page);
        fill_equipment_to_pb(paginated_sas, pb_creator, depth);
        pb_creator.make_paginate(sas_per_line.size(), start_page, count, paginated_sas.size());
    }
    catch(const ptref::parsing_error& parse_error) {
        pb_creator.fill_pb_error(pbnavitia::Error::unable_to_parse, "Unable to parse filter" + parse_error.more);
        return;
    } catch(const ptref::ptref_error& ptref_error) {
        pb_creator.fill_pb_error(pbnavitia::Error::bad_filter, "ptref : "  + ptref_error.more);
        return;
    }
}

} // namespace equipment
} // namespace navitia
