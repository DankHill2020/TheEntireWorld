#include "tc_force_tree.h"

#include <algorithm>
#include <cmath>
#include <limits>
#include <numeric>
#include <stdexcept>

namespace tc::runtime {
namespace {

double component(const SpatialPoint& point, int axis) {
    if (axis == 0) return point.x;
    if (axis == 1) return point.y;
    return point.z;
}

}  // namespace

BarnesHutMassTree::BarnesHutMassTree(std::vector<MassPoint> bodies) : bodies_(std::move(bodies)) {
    bodies_.erase(std::remove_if(bodies_.begin(), bodies_.end(), [](const MassPoint& body) {
        return !std::isfinite(body.position_meters.x) || !std::isfinite(body.position_meters.y) ||
               !std::isfinite(body.position_meters.z) || !std::isfinite(body.mass_kilograms) || body.mass_kilograms <= 0.0;
    }), bodies_.end());
    if (bodies_.empty()) return;

    SpatialPoint minimum=bodies_.front().position_meters,maximum=minimum;
    for(const auto& body:bodies_){
        minimum.x=std::min(minimum.x,body.position_meters.x);minimum.y=std::min(minimum.y,body.position_meters.y);minimum.z=std::min(minimum.z,body.position_meters.z);
        maximum.x=std::max(maximum.x,body.position_meters.x);maximum.y=std::max(maximum.y,body.position_meters.y);maximum.z=std::max(maximum.z,body.position_meters.z);
    }
    const SpatialPoint center{minimum.x+(maximum.x-minimum.x)*0.5,minimum.y+(maximum.y-minimum.y)*0.5,minimum.z+(maximum.z-minimum.z)*0.5};
    double half_extent=0.5*std::max({maximum.x-minimum.x,maximum.y-minimum.y,maximum.z-minimum.z});
    half_extent=std::max(1.0e-12,std::nextafter(half_extent,std::numeric_limits<double>::infinity()));
    std::vector<std::size_t> indices(bodies_.size());std::iota(indices.begin(),indices.end(),0U);
    nodes_.reserve(bodies_.size()*2U);root_=build_node(indices,center,half_extent,0);
}

int BarnesHutMassTree::build_node(const std::vector<std::size_t>& indices,const SpatialPoint& center,double half_extent,int depth){
    const int node_index=static_cast<int>(nodes_.size());nodes_.push_back({});
    nodes_[node_index].center=center;nodes_[node_index].half_extent=half_extent;
    for(const auto index:indices){
        const auto& body=bodies_[index];const double next_mass=nodes_[node_index].mass+body.mass_kilograms;
        nodes_[node_index].center_of_mass.x=(nodes_[node_index].center_of_mass.x*nodes_[node_index].mass+body.position_meters.x*body.mass_kilograms)/next_mass;
        nodes_[node_index].center_of_mass.y=(nodes_[node_index].center_of_mass.y*nodes_[node_index].mass+body.position_meters.y*body.mass_kilograms)/next_mass;
        nodes_[node_index].center_of_mass.z=(nodes_[node_index].center_of_mass.z*nodes_[node_index].mass+body.position_meters.z*body.mass_kilograms)/next_mass;
        nodes_[node_index].mass=next_mass;
    }
    if(indices.size()<=4U||depth>=48){nodes_[node_index].body_indices=indices;return node_index;}
    std::array<std::vector<std::size_t>,8> buckets;
    for(const auto index:indices){const auto& point=bodies_[index].position_meters;const int octant=(point.x>=center.x?1:0)|(point.y>=center.y?2:0)|(point.z>=center.z?4:0);buckets[octant].push_back(index);}
    const double child_half=half_extent*0.5;
    for(int octant=0;octant<8;++octant)if(!buckets[octant].empty()){
        const SpatialPoint child_center{center.x+((octant&1)?child_half:-child_half),center.y+((octant&2)?child_half:-child_half),center.z+((octant&4)?child_half:-child_half)};
        nodes_[node_index].children[octant]=build_node(buckets[octant],child_center,child_half,depth+1);
    }
    return node_index;
}

SpatialPoint BarnesHutMassTree::acceleration_at(std::uint32_t target_id,const SpatialPoint& position,double gravitational_constant,double softening_meters,double theta)const{
    if(!std::isfinite(theta)||theta<=0.0)throw std::invalid_argument("Barnes-Hut theta must be finite and positive");
    SpatialPoint acceleration{};if(root_>=0)accumulate(root_,target_id,position,gravitational_constant,softening_meters*softening_meters,theta,acceleration);return acceleration;
}

void BarnesHutMassTree::accumulate(int node_index,std::uint32_t target_id,const SpatialPoint& position,double constant,double softening_squared,double theta,SpatialPoint& acceleration)const{
    const auto& node=nodes_[node_index];
    if(!node.body_indices.empty()){
        for(const auto index:node.body_indices){const auto& body=bodies_[index];if(body.id==target_id)continue;const double dx=body.position_meters.x-position.x,dy=body.position_meters.y-position.y,dz=body.position_meters.z-position.z;const double r2=dx*dx+dy*dy+dz*dz+softening_squared;const double factor=constant*body.mass_kilograms/(r2*std::sqrt(r2));acceleration.x+=dx*factor;acceleration.y+=dy*factor;acceleration.z+=dz*factor;}return;
    }
    const double dx=node.center_of_mass.x-position.x,dy=node.center_of_mass.y-position.y,dz=node.center_of_mass.z-position.z;const double distance=std::sqrt(dx*dx+dy*dy+dz*dz);
    const bool contains_target=std::fabs(position.x-node.center.x)<=node.half_extent&&std::fabs(position.y-node.center.y)<=node.half_extent&&std::fabs(position.z-node.center.z)<=node.half_extent;
    if(!contains_target&&distance>0.0&&(2.0*node.half_extent)/distance<theta){const double r2=distance*distance+softening_squared;const double factor=constant*node.mass/(r2*std::sqrt(r2));acceleration.x+=dx*factor;acceleration.y+=dy*factor;acceleration.z+=dz*factor;return;}
    for(const int child:node.children)if(child>=0)accumulate(child,target_id,position,constant,softening_squared,theta,acceleration);
}

}  // namespace tc::runtime
