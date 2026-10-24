#include "tc_gpu_renderer.h"
#include "tc_skin_source_validation.h"

#include <algorithm>
#include <array>
#include <cctype>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <fstream>
#include <iostream>
#include <limits>
#include <sstream>
#include <thread>
#include <unordered_map>
#include <vector>

#if defined(_WIN32)
#include <d3d11.h>
#include <d3dcompiler.h>
#include <d2d1_1.h>
#include <DirectXMath.h>
#include <wincodec.h>
#include <wrl/client.h>
#endif

namespace tc::runtime {

#if defined(_WIN32)
using Microsoft::WRL::ComPtr;
using namespace DirectX;

namespace {

std::string path_utf8(const std::filesystem::path& path) {
    const auto text = path.u8string();
    return std::string(text.begin(), text.end());
}

struct Vertex { XMFLOAT3 position; XMFLOAT3 normal; XMFLOAT2 uv; };
struct Constants {
    XMFLOAT4X4 world;
    XMFLOAT4X4 view_projection;
    XMFLOAT4X4 light_view_projection;
    XMFLOAT4X4 previous_world;
    XMFLOAT4X4 previous_view_projection;
    XMFLOAT4 base_metallic;
    XMFLOAT4 light_roughness;
    XMFLOAT4 sun_color_intensity;
    XMFLOAT4 camera;
    XMFLOAT4 environment;
    XMFLOAT4 sky;
    XMFLOAT4 ground;
    XMFLOAT4 style;
    std::array<XMFLOAT4,8> bounce_position_radius;
    std::array<XMFLOAT4,8> bounce_color_intensity;
    XMFLOAT4 bounce_settings;
};

struct PostConstants {
    XMFLOAT4 temporal;
    XMFLOAT4 display;
};

struct SkyConstants {
    XMFLOAT4X4 inverse_view_projection;
    XMFLOAT4 camera;
    XMFLOAT4 sun_direction_radius;
    XMFLOAT4 sun_color_intensity;
    XMFLOAT4 sky;
    XMFLOAT4 ground;
    XMFLOAT4 atmosphere;
};

struct SkinConstants { std::uint32_t enabled{0}; std::uint32_t padding[3]{}; };
struct GpuSkinVertex {
    XMFLOAT4 rest_position{};
    XMUINT4 metadata{};
};
struct GpuSkinInfluence { std::uint32_t joint{}; float weight{}; };
static_assert(sizeof(GpuSkinVertex)==32 && sizeof(GpuSkinInfluence)==8,
              "GPU skin buffers must match their HLSL structured-buffer layouts.");

constexpr Vertex vertices[] = {
    {{-0.5F,-0.5F,-0.5F},{0,0,-1},{0,1}},{{0.5F,-0.5F,-0.5F},{0,0,-1},{1,1}},{{0.5F,0.5F,-0.5F},{0,0,-1},{1,0}},{{-0.5F,0.5F,-0.5F},{0,0,-1},{0,0}},
    {{-0.5F,-0.5F,0.5F},{0,0,1},{0,1}},{{0.5F,-0.5F,0.5F},{0,0,1},{1,1}},{{0.5F,0.5F,0.5F},{0,0,1},{1,0}},{{-0.5F,0.5F,0.5F},{0,0,1},{0,0}},
    {{-0.5F,-0.5F,-0.5F},{-1,0,0},{0,1}},{{-0.5F,0.5F,-0.5F},{-1,0,0},{1,1}},{{-0.5F,0.5F,0.5F},{-1,0,0},{1,0}},{{-0.5F,-0.5F,0.5F},{-1,0,0},{0,0}},
    {{0.5F,-0.5F,-0.5F},{1,0,0},{0,1}},{{0.5F,0.5F,-0.5F},{1,0,0},{1,1}},{{0.5F,0.5F,0.5F},{1,0,0},{1,0}},{{0.5F,-0.5F,0.5F},{1,0,0},{0,0}},
    {{-0.5F,-0.5F,-0.5F},{0,-1,0},{0,1}},{{-0.5F,-0.5F,0.5F},{0,-1,0},{1,1}},{{0.5F,-0.5F,0.5F},{0,-1,0},{1,0}},{{0.5F,-0.5F,-0.5F},{0,-1,0},{0,0}},
    {{-0.5F,0.5F,-0.5F},{0,1,0},{0,1}},{{-0.5F,0.5F,0.5F},{0,1,0},{1,1}},{{0.5F,0.5F,0.5F},{0,1,0},{1,0}},{{0.5F,0.5F,-0.5F},{0,1,0},{0,0}},
};
constexpr std::uint16_t indices[] = {0,2,1,0,3,2,4,5,6,4,6,7,8,10,9,8,11,10,12,13,14,12,14,15,16,18,17,16,19,18,20,21,22,20,22,23};

constexpr const char* shader_source = R"(
cbuffer Scene : register(b0) { matrix world; matrix viewProjection; matrix lightViewProjection; matrix previousWorld; matrix previousViewProjection; float4 baseMetallic; float4 lightRoughness; float4 sunColorIntensity; float4 cameraPosition; float4 environmentSettings; float4 skySettings; float4 groundSettings; float4 styleSettings; float4 bouncePositionRadius[8]; float4 bounceColorIntensity[8]; float4 bounceSettings; };
cbuffer Post : register(b1) { float4 temporalSettings; float4 displaySettings; };
cbuffer Sky : register(b2) { matrix inverseViewProjection; float4 skyCamera; float4 skySunDirectionRadius; float4 skySunColorIntensity; float4 authoredSky; float4 authoredGround; float4 atmosphereSettings; };
cbuffer Skin : register(b3) { uint skinEnabled; uint3 skinPadding; };
struct SkinVertex { float4 restPosition; uint4 metadata; };
struct SkinInfluence { uint joint; float weight; };
StructuredBuffer<SkinVertex> skinVertices : register(t10);
StructuredBuffer<float4x4> skinPalette : register(t11);
StructuredBuffer<SkinInfluence> skinInfluences : register(t12);
struct VSIn { float3 position:POSITION; float3 normal:NORMAL; float2 uv:TEXCOORD0; uint vertexId:SV_VertexID; };
struct VSOut { float4 position:SV_POSITION; float3 worldPosition:TEXCOORD0; float3 normal:TEXCOORD1; float4 lightPosition:TEXCOORD2; float2 uv:TEXCOORD3; float4 currentClip:TEXCOORD4; float4 previousClip:TEXCOORD5; };
void ResolveSkin(VSIn input,out float3 position,out float3 normal){position=input.position;normal=input.normal;if(skinEnabled==0)return;SkinVertex skin=skinVertices[input.vertexId];float4 source=float4(skin.restPosition.xyz,1);float4 skinned=0;float3 skinnedNormal=0;float total=0;[loop]for(uint influence=0;influence<skin.metadata.x;influence++){SkinInfluence item=skinInfluences[skin.metadata.y+influence];if(item.weight>0){float4x4 joint=skinPalette[item.joint];skinned+=mul(source,joint)*item.weight;skinnedNormal+=mul(float4(input.normal,0),joint).xyz*item.weight;total+=item.weight;}}if(total>0.000001){position=skinned.xyz/total;normal=normalize(skinnedNormal/total);}}
VSOut VSMain(VSIn input) { VSOut o;float3 localPosition,localNormal;ResolveSkin(input,localPosition,localNormal);float4 wp=mul(float4(localPosition,1),world); o.position=mul(wp,viewProjection); o.currentClip=o.position; o.previousClip=mul(mul(float4(localPosition,1),previousWorld),previousViewProjection); o.worldPosition=wp.xyz; o.normal=normalize(mul(float4(localNormal,0),world).xyz); o.lightPosition=mul(wp,lightViewProjection); o.uv=input.uv; return o; }
float DistributionGGX(float3 N,float3 H,float r){float a=r*r;float a2=a*a;float n=max(dot(N,H),0);float d=n*n*(a2-1)+1;return a2/max(0.001,3.14159265*d*d);}
float GeometrySchlick(float n,float r){float k=(r+1)*(r+1)/8;return n/(n*(1-k)+k);}
float3 ACES(float3 x){float a=2.51,b=0.03,c=2.43,d=0.59,e=0.14;return saturate((x*(a*x+b))/(x*(c*x+d)+e));}
float2 LatLong(float3 d){d=normalize(d);return float2(atan2(d.z,d.x)/6.2831853+0.5,acos(clamp(d.y,-1,1))/3.14159265);}
Texture2D shadowMap:register(t0); Texture2D baseMap:register(t1); Texture2D normalMap:register(t2); Texture2D roughnessMap:register(t3); Texture2D metallicMap:register(t4); Texture2D emissionMap:register(t5); Texture2D environmentMap:register(t6);
Texture2D currentFrame:register(t7); Texture2D motionMap:register(t8); Texture2D historyMap:register(t9);
Texture2D uiMap:register(t12);
SamplerComparisonState shadowSampler:register(s0); SamplerState materialSampler:register(s1);
float FilterShadow(float4 lightPosition,float ndl){float3 p=lightPosition.xyz/lightPosition.w;float2 uv=float2(p.x*0.5+0.5,-p.y*0.5+0.5);if(any(uv<0)||any(uv>1)||p.z<0||p.z>1)return 1;float bias=max(0.0008*(1-ndl),0.00018);float result=0,filterRadius=max(1,styleSettings.w);[unroll]for(int y=-2;y<=2;y++){[unroll]for(int x=-2;x<=2;x++){result+=shadowMap.SampleCmpLevelZero(shadowSampler,uv+float2(x,y)*filterRadius/2048.0,p.z-bias);}}return result/25.0;}
struct SurfaceOut { float4 color:SV_TARGET0; float2 motion:SV_TARGET1; };
float3 IndirectLight(float3 base,float3 N,float3 V,float3 worldPosition,float rough,float metal,float3 F){
    if(environmentSettings.z<0.5)return 0;
    float hemisphereWeight=saturate(N.y*0.5+0.5);
    float3 hemisphere=lerp(groundSettings.rgb,skySettings.rgb,hemisphereWeight)*base*(1-metal);
    float3 dynamicBounce=0;[unroll]for(int source=0;source<8;source++){if(source>=int(bounceSettings.x))break;float3 delta=bouncePositionRadius[source].xyz-worldPosition;float distanceSquared=dot(delta,delta);if(distanceSquared>1e-6){float distance=sqrt(distanceSquared),radius=max(0.001,bouncePositionRadius[source].w);float attenuation=pow(saturate(1-distance/radius),2);dynamicBounce+=bounceColorIntensity[source].rgb*max(dot(N,delta/distance),0)*attenuation*bounceColorIntensity[source].w;}}
    if(environmentSettings.z<1.5)return hemisphere*environmentSettings.w+dynamicBounce;
    float3 envDiffuse=environmentMap.SampleLevel(materialSampler,LatLong(N),rough*5).rgb*base*(1-metal);
    float3 envSpec=environmentMap.SampleLevel(materialSampler,LatLong(reflect(-V,N)),rough*5).rgb*F;
    return (hemisphere*0.35+(envDiffuse+envSpec)*environmentSettings.x)*environmentSettings.w+dynamicBounce;
}
float3 ShadeSurface(float3 base,float3 N,float3 V,float3 worldPosition,float rough,float metal,float shadow,float3 emission){
    if(environmentSettings.y>2.5)return base+emission;
    float3 L=normalize(-lightRoughness.xyz),H=normalize(V+L);
    float rawNdl=dot(N,L),ndl=max(rawNdl,0),ndv=max(dot(N,V),0.001),ndh=max(dot(N,H),0),hdv=max(dot(H,V),0);
    float3 F0=lerp(0.04.xxx,base,metal),F=F0+(1-F0)*pow(1-hdv,5);
    float3 indirect=IndirectLight(base,N,V,worldPosition,rough,metal,F);
    if(environmentSettings.y>1.5){
        float bands=max(2,styleSettings.x),band=floor(saturate(rawNdl)*bands)/(bands-1);
        float graphicShadow=lerp(0.3,1.0,step(0.55,shadow));
        float3 direct=base*band*graphicShadow*sunColorIntensity.rgb*sunColorIntensity.w;
        float3 specular=step(0.82+rough*0.12,ndh)*F*sunColorIntensity.rgb*sunColorIntensity.w;
        float rim=step(0.62,1-ndv)*styleSettings.y;
        return indirect+direct+specular+rim*skySettings.rgb+emission;
    }
    float distribution=DistributionGGX(N,H,rough);
    float geometry=GeometrySchlick(ndv,rough)*GeometrySchlick(ndl,rough);
    float3 specular=F*distribution*geometry/max(0.004,4*ndv*ndl);
    float3 diffuse=base*(1-metal)/3.14159265;
    if(environmentSettings.y>0.5){
        float wrapped=smoothstep(-0.2,0.85,rawNdl),rim=pow(saturate(1-ndv),3)*styleSettings.y;
        float3 direct=(base*(1-metal)*wrapped+specular*ndl)*sunColorIntensity.rgb*sunColorIntensity.w*shadow;
        return indirect+direct+rim*skySettings.rgb+emission;
    }
    return indirect+(diffuse+specular)*ndl*sunColorIntensity.rgb*sunColorIntensity.w*shadow+emission;
}
SurfaceOut PSMain(VSOut input) {
    SurfaceOut output;float3 base=baseMetallic.xyz*baseMap.Sample(materialSampler,input.uv).rgb;
    float3 N=normalize(input.normal),mapN=normalMap.Sample(materialSampler,input.uv).xyz*2-1;
    float3 dp1=ddx(input.worldPosition),dp2=ddy(input.worldPosition);float2 duv1=ddx(input.uv),duv2=ddy(input.uv);
    float3 T=normalize(dp1*duv2.y-dp2*duv1.y),B=normalize(-dp1*duv2.x+dp2*duv1.x);N=normalize(T*mapN.x+B*mapN.y+N*mapN.z);
    float3 V=normalize(cameraPosition.xyz-input.worldPosition);float rough=max(lightRoughness.w*roughnessMap.Sample(materialSampler,input.uv).r,0.045);
    float metal=saturate(baseMetallic.w*metallicMap.Sample(materialSampler,input.uv).r),ndl=max(dot(N,normalize(-lightRoughness.xyz)),0);
    float shadow=lerp(1.0,FilterShadow(input.lightPosition,ndl),styleSettings.z);float3 emission=emissionMap.Sample(materialSampler,input.uv).rgb;
    output.color=float4(ShadeSurface(base,N,V,input.worldPosition,rough,metal,shadow,emission)*cameraPosition.w,1);
    float2 current=input.currentClip.xy/max(input.currentClip.w,0.0001),previous=input.previousClip.xy/max(input.previousClip.w,0.0001);
    output.motion=(current-previous)*float2(0.5,-0.5);return output;
}
struct PostOut { float4 position:SV_POSITION; float2 uv:TEXCOORD0; };
PostOut VSPost(uint vertexId:SV_VertexID){PostOut output;float2 uv=float2((vertexId<<1)&2,vertexId&2);output.uv=uv;output.position=float4(uv*float2(2,-2)+float2(-1,1),0,1);return output;}
float4 PSAtmosphere(PostOut input):SV_TARGET {
    float2 ndc=float2(input.uv.x*2-1,1-input.uv.y*2);float4 farPoint=mul(float4(ndc,1,1),inverseViewProjection);
    float3 direction=normalize(farPoint.xyz/max(1e-6,farPoint.w)-skyCamera.xyz);float up=direction.y;
    float3 sunDirection=normalize(-skySunDirectionRadius.xyz);float sunAmount=saturate(dot(direction,sunDirection));
    float density=max(0.01,atmosphereSettings.x),haze=max(0,atmosphereSettings.y),falloff=max(0.5,atmosphereSettings.z);
    float horizon=pow(saturate(1-abs(up)),falloff);float airMass=1/max(0.06,up+0.16);
    float3 rayleigh=float3(0.16,0.36,1.0)*(1-exp(-density*airMass*0.22));
    float mie=pow(sunAmount,8)*horizon*haze+pow(sunAmount,64)*haze*0.2;
    float day=saturate(sunDirection.y*4+0.35);float3 skyColor=authoredSky.rgb*(0.22+0.78*day)+rayleigh*skySunColorIntensity.rgb;
    skyColor+=mie*float3(1.0,0.58,0.28)*skySunColorIntensity.w;
    float sunRadius=radians(max(0.01,skySunDirectionRadius.w));float sunDisk=smoothstep(cos(sunRadius*1.8),cos(sunRadius*0.45),sunAmount);
    skyColor+=sunDisk*skySunColorIntensity.rgb*skySunColorIntensity.w*12.0;
    float groundBlend=smoothstep(-0.12,0.02,up);float3 groundColor=authoredGround.rgb*(0.35+0.65*day)+horizon*authoredSky.rgb*0.25;
    return float4(lerp(groundColor,skyColor,groundBlend)*skyCamera.w,1);
}
float4 PSTemporal(PostOut input):SV_TARGET {float2 velocity=motionMap.SampleLevel(materialSampler,input.uv,0).xy;float3 current=currentFrame.SampleLevel(materialSampler,input.uv,0).rgb;float3 minimum=current,maximum=current;[unroll]for(int y=-1;y<=1;y++){[unroll]for(int x=-1;x<=1;x++){float3 sampleValue=currentFrame.SampleLevel(materialSampler,input.uv+float2(x,y)*temporalSettings.xy,0).rgb;minimum=min(minimum,sampleValue);maximum=max(maximum,sampleValue);}}float2 historyUv=input.uv-velocity;float valid=temporalSettings.z*step(0,historyUv.x)*step(historyUv.x,1)*step(0,historyUv.y)*step(historyUv.y,1);float3 history=clamp(historyMap.SampleLevel(materialSampler,historyUv,0).rgb,minimum,maximum);return float4(lerp(current,history,temporalSettings.w*valid),1);}
float4 PSDisplay(PostOut input):SV_TARGET {float3 center=historyMap.SampleLevel(materialSampler,input.uv,0).rgb;float3 neighbors=0.25*(historyMap.SampleLevel(materialSampler,input.uv+float2(displaySettings.x,0),0).rgb+historyMap.SampleLevel(materialSampler,input.uv-float2(displaySettings.x,0),0).rgb+historyMap.SampleLevel(materialSampler,input.uv+float2(0,displaySettings.y),0).rgb+historyMap.SampleLevel(materialSampler,input.uv-float2(0,displaySettings.y),0).rgb);float3 sharpened=max(0,center+(center-neighbors)*displaySettings.z);return float4(pow(ACES(sharpened),1/2.2),1);}
float4 PSUi(PostOut input):SV_TARGET {return uiMap.SampleLevel(materialSampler,input.uv,0);}
float4 VSShadow(VSIn input):SV_POSITION { float3 position,normal;ResolveSkin(input,position,normal);return mul(mul(float4(position,1),world),lightViewProjection); }
)";

bool compile_shader(const char* entry, const char* profile, ComPtr<ID3DBlob>& blob, std::string& error) {
    ComPtr<ID3DBlob> messages;
    const HRESULT status = D3DCompile(shader_source, std::strlen(shader_source), "tc_runtime.hlsl", nullptr, nullptr, entry, profile,
                                      D3DCOMPILE_ENABLE_STRICTNESS, 0, &blob, &messages);
    if (FAILED(status)) {
        error = messages ? std::string(static_cast<const char*>(messages->GetBufferPointer()), messages->GetBufferSize()) : "D3D shader compilation failed.";
        return false;
    }
    return true;
}

}  // namespace

class GpuRenderer::Implementation {
public:
    explicit Implementation(RenderBackend requested):requested_backend_(requested){}
    void set_vsync(bool enabled) noexcept { vsync_=enabled; }
    void set_cpu_skinning_diagnostic(bool enabled) noexcept { cpu_skinning_diagnostic_=enabled; }
    void set_ui_scale(float scale) noexcept { ui_scale_=std::clamp(scale,0.75F,10.0F);ui_content_key_.clear(); }
    RenderBackend backend()const noexcept{return requested_backend_==RenderBackend::automatic?RenderBackend::d3d11:requested_backend_;}
    RenderBackendCapabilities capabilities()const{switch(backend()){case RenderBackend::d3d11:return {RenderBackend::d3d11,"Direct3D 11",true,true,true,true,false};case RenderBackend::d3d12:return {RenderBackend::d3d12,"Direct3D 12",false,false,false,false,false};case RenderBackend::vulkan:return {RenderBackend::vulkan,"Vulkan",false,false,false,false,false};case RenderBackend::metal:return {RenderBackend::metal,"Metal",false,false,false,false,false};default:return {RenderBackend::null_backend,"Null",true,false,false,false,false};}}
    bool initialize(void* window, int width, int height, std::string& error) {
        if(requested_backend_!=RenderBackend::automatic&&requested_backend_!=RenderBackend::d3d11){error="Requested renderer backend is not available in this build.";return false;}
        const HRESULT com_status=CoInitializeEx(nullptr,COINIT_APARTMENTTHREADED);
        com_lifetime_.initialized=SUCCEEDED(com_status);
        DXGI_SWAP_CHAIN_DESC description{}; description.BufferCount=2; description.BufferDesc.Width=width; description.BufferDesc.Height=height;
        description.BufferDesc.Format=DXGI_FORMAT_B8G8R8A8_UNORM; description.BufferUsage=DXGI_USAGE_RENDER_TARGET_OUTPUT;
        description.OutputWindow=static_cast<HWND>(window); description.SampleDesc.Count=1; description.Windowed=TRUE; description.SwapEffect=DXGI_SWAP_EFFECT_FLIP_DISCARD;
        D3D_FEATURE_LEVEL level{};
        HRESULT status=D3D11CreateDeviceAndSwapChain(nullptr,D3D_DRIVER_TYPE_HARDWARE,nullptr,D3D11_CREATE_DEVICE_BGRA_SUPPORT,nullptr,0,D3D11_SDK_VERSION,&description,&swap_chain_,&device_,&level,&context_);
        if(FAILED(status)){error="D3D11 hardware device creation failed.";return false;}
        ComPtr<IDXGIDevice> dxgi_device;
        ComPtr<IDXGIAdapter> adapter;
        ComPtr<IDXGIAdapter1> adapter1;
        DXGI_ADAPTER_DESC1 adapter_description{};
        if(SUCCEEDED(device_.As(&dxgi_device))&&
           SUCCEEDED(dxgi_device->GetAdapter(&adapter))&&
           SUCCEEDED(adapter.As(&adapter1))&&
           SUCCEEDED(adapter1->GetDesc1(&adapter_description))){
            const int utf8_size=WideCharToMultiByte(CP_UTF8,0,adapter_description.Description,-1,nullptr,0,nullptr,nullptr);
            if(utf8_size>1){
                std::vector<char> utf8(static_cast<std::size_t>(utf8_size));
                if(WideCharToMultiByte(CP_UTF8,0,adapter_description.Description,-1,utf8.data(),utf8_size,nullptr,nullptr)>0)
                    adapter_info_.name=utf8.data();
            }
            adapter_info_.vendor_id=adapter_description.VendorId;
            adapter_info_.device_id=adapter_description.DeviceId;
            adapter_info_.dedicated_video_memory_bytes=adapter_description.DedicatedVideoMemory;
            adapter_info_.software=(adapter_description.Flags&DXGI_ADAPTER_FLAG_SOFTWARE)!=0;
        }
        D2D1CreateFactory(D2D1_FACTORY_TYPE_SINGLE_THREADED,__uuidof(ID2D1Factory1),nullptr,
                          reinterpret_cast<void**>(d2d_factory_.GetAddressOf()));
        ComPtr<ID3DBlob> vs_blob,ps_blob,shadow_blob,post_vs_blob,temporal_blob,display_blob,atmosphere_blob,ui_blob;
        if(!compile_shader("VSMain","vs_5_0",vs_blob,error)||!compile_shader("PSMain","ps_5_0",ps_blob,error)||
           !compile_shader("VSShadow","vs_5_0",shadow_blob,error)||!compile_shader("VSPost","vs_5_0",post_vs_blob,error)||
           !compile_shader("PSTemporal","ps_5_0",temporal_blob,error)||!compile_shader("PSDisplay","ps_5_0",display_blob,error)||
           !compile_shader("PSUi","ps_5_0",ui_blob,error)||
           !compile_shader("PSAtmosphere","ps_5_0",atmosphere_blob,error))return false;
        device_->CreateVertexShader(vs_blob->GetBufferPointer(),vs_blob->GetBufferSize(),nullptr,&vertex_shader_);
        device_->CreatePixelShader(ps_blob->GetBufferPointer(),ps_blob->GetBufferSize(),nullptr,&pixel_shader_);
        device_->CreateVertexShader(shadow_blob->GetBufferPointer(),shadow_blob->GetBufferSize(),nullptr,&shadow_shader_);
        device_->CreateVertexShader(post_vs_blob->GetBufferPointer(),post_vs_blob->GetBufferSize(),nullptr,&post_vertex_shader_);
        device_->CreatePixelShader(temporal_blob->GetBufferPointer(),temporal_blob->GetBufferSize(),nullptr,&temporal_shader_);
        device_->CreatePixelShader(display_blob->GetBufferPointer(),display_blob->GetBufferSize(),nullptr,&display_shader_);
        device_->CreatePixelShader(ui_blob->GetBufferPointer(),ui_blob->GetBufferSize(),nullptr,&ui_shader_);
        device_->CreatePixelShader(atmosphere_blob->GetBufferPointer(),atmosphere_blob->GetBufferSize(),nullptr,&atmosphere_shader_);
        D3D11_INPUT_ELEMENT_DESC layout[]={{"POSITION",0,DXGI_FORMAT_R32G32B32_FLOAT,0,0,D3D11_INPUT_PER_VERTEX_DATA,0},{"NORMAL",0,DXGI_FORMAT_R32G32B32_FLOAT,0,12,D3D11_INPUT_PER_VERTEX_DATA,0},{"TEXCOORD",0,DXGI_FORMAT_R32G32_FLOAT,0,24,D3D11_INPUT_PER_VERTEX_DATA,0}};
        device_->CreateInputLayout(layout,3,vs_blob->GetBufferPointer(),vs_blob->GetBufferSize(),&layout_);
        D3D11_BUFFER_DESC buffer{};buffer.Usage=D3D11_USAGE_IMMUTABLE;buffer.BindFlags=D3D11_BIND_VERTEX_BUFFER;buffer.ByteWidth=sizeof(vertices);D3D11_SUBRESOURCE_DATA data{vertices};device_->CreateBuffer(&buffer,&data,&vertex_buffer_);
        buffer.BindFlags=D3D11_BIND_INDEX_BUFFER;buffer.ByteWidth=sizeof(indices);data.pSysMem=indices;device_->CreateBuffer(&buffer,&data,&index_buffer_);
        buffer.Usage=D3D11_USAGE_DYNAMIC;buffer.CPUAccessFlags=D3D11_CPU_ACCESS_WRITE;buffer.BindFlags=D3D11_BIND_CONSTANT_BUFFER;buffer.ByteWidth=sizeof(Constants);device_->CreateBuffer(&buffer,nullptr,&constants_);
        buffer.ByteWidth=sizeof(PostConstants);device_->CreateBuffer(&buffer,nullptr,&post_constants_);
        buffer.ByteWidth=sizeof(SkyConstants);device_->CreateBuffer(&buffer,nullptr,&sky_constants_);
        buffer.ByteWidth=sizeof(SkinConstants);device_->CreateBuffer(&buffer,nullptr,&skin_constants_);
        D3D11_SAMPLER_DESC sampler{};sampler.Filter=D3D11_FILTER_COMPARISON_MIN_MAG_LINEAR_MIP_POINT;sampler.AddressU=sampler.AddressV=sampler.AddressW=D3D11_TEXTURE_ADDRESS_BORDER;sampler.ComparisonFunc=D3D11_COMPARISON_LESS_EQUAL;sampler.BorderColor[0]=sampler.BorderColor[1]=sampler.BorderColor[2]=sampler.BorderColor[3]=1;device_->CreateSamplerState(&sampler,&shadow_sampler_);
        sampler={};sampler.Filter=D3D11_FILTER_ANISOTROPIC;sampler.AddressU=sampler.AddressV=sampler.AddressW=D3D11_TEXTURE_ADDRESS_WRAP;sampler.MaxAnisotropy=8;sampler.MaxLOD=D3D11_FLOAT32_MAX;device_->CreateSamplerState(&sampler,&material_sampler_);
        D3D11_RASTERIZER_DESC raster{};raster.FillMode=D3D11_FILL_SOLID;raster.CullMode=D3D11_CULL_BACK;raster.DepthClipEnable=TRUE;device_->CreateRasterizerState(&raster,&default_rasterizer_);
        raster.DepthBias=600;raster.SlopeScaledDepthBias=1.5F;raster.DepthBiasClamp=0.01F;device_->CreateRasterizerState(&raster,&shadow_rasterizer_);
        D3D11_BLEND_DESC ui_blend{};ui_blend.RenderTarget[0].BlendEnable=TRUE;
        ui_blend.RenderTarget[0].SrcBlend=D3D11_BLEND_ONE;
        ui_blend.RenderTarget[0].DestBlend=D3D11_BLEND_INV_SRC_ALPHA;
        ui_blend.RenderTarget[0].BlendOp=D3D11_BLEND_OP_ADD;
        ui_blend.RenderTarget[0].SrcBlendAlpha=D3D11_BLEND_ONE;
        ui_blend.RenderTarget[0].DestBlendAlpha=D3D11_BLEND_INV_SRC_ALPHA;
        ui_blend.RenderTarget[0].BlendOpAlpha=D3D11_BLEND_OP_ADD;
        ui_blend.RenderTarget[0].RenderTargetWriteMask=D3D11_COLOR_WRITE_ENABLE_ALL;
        device_->CreateBlendState(&ui_blend,&ui_blend_state_);
        if(FAILED(CoCreateInstance(CLSID_WICImagingFactory2,nullptr,CLSCTX_INPROC_SERVER,IID_PPV_ARGS(&wic_)))){
            error="Could not initialize Windows Imaging Component for UI and textures.";return false;
        }
        create_solid(0xFFFFFFFF,white_texture_);create_solid(0xFFFF8080,normal_texture_);create_solid(0xFF000000,black_texture_);
        if(!create_shadow(error)||!create_gpu_timers(error))return false;return resize(width,height,error);
    }
    bool resize(int width,int height,std::string& error){
        if(!swap_chain_){error="Cannot resize before the swap chain is initialized.";return false;}
        // Restoring a minimized window can send WM_SIZE with the unchanged client size.
        // The offscreen targets and UI texture are still valid; rebuilding them here
        // introduces a visible redraw/upload hitch for no change in presentation size.
        if(width>0&&height>0&&width==width_&&height==height_&&ready()){
            error.clear();return true;
        }
        context_->OMSetRenderTargets(0,nullptr,nullptr);
        render_target_.Reset();
        back_buffer_.Reset();display_target_.Reset();display_texture_.Reset();
        for(auto& [path,image]:ui_image_cache_)image.bitmap.Reset();
        ui_target_.Reset();ui_bitmap_.Reset();ui_brush_.Reset();ui_resource_.Reset();ui_texture_.Reset();
        ui_content_key_.clear();
        const HRESULT resize_status=swap_chain_->ResizeBuffers(0,width,height,DXGI_FORMAT_UNKNOWN,0);
        if(FAILED(resize_status)){
            error="Could not resize the swap chain (HRESULT "+std::to_string(static_cast<unsigned long>(resize_status))+"; device reason "+
                  std::to_string(static_cast<unsigned long>(device_->GetDeviceRemovedReason()))+").";
            return false;
        }
        ComPtr<ID3D11Texture2D> back;
        if(FAILED(swap_chain_->GetBuffer(0,IID_PPV_ARGS(&back)))||FAILED(device_->CreateRenderTargetView(back.Get(),nullptr,&render_target_))){error="Could not create the display target.";return false;}
        D3D11_TEXTURE2D_DESC display_desc{};
        back->GetDesc(&display_desc);
        display_desc.BindFlags=D3D11_BIND_RENDER_TARGET;
        display_desc.MiscFlags=0;
        if(FAILED(device_->CreateTexture2D(&display_desc,nullptr,&display_texture_))||
           FAILED(device_->CreateRenderTargetView(display_texture_.Get(),nullptr,&display_target_))){
            error="Could not create the offscreen display target.";return false;
        }
        back_buffer_=back;
        if(d2d_factory_&&wic_){
            if(FAILED(wic_->CreateBitmap(width,height,GUID_WICPixelFormat32bppPBGRA,
                                         WICBitmapCacheOnLoad,&ui_bitmap_))){
                error="Could not create the UI bitmap.";return false;
            }
            const auto properties=D2D1::RenderTargetProperties(D2D1_RENDER_TARGET_TYPE_SOFTWARE,
                D2D1::PixelFormat(DXGI_FORMAT_B8G8R8A8_UNORM,D2D1_ALPHA_MODE_PREMULTIPLIED),96.0F,96.0F);
            if(FAILED(d2d_factory_->CreateWicBitmapRenderTarget(ui_bitmap_.Get(),properties,&ui_target_))){
                error="Could not create the UI software render target.";return false;
            }
            ui_target_->SetTextAntialiasMode(D2D1_TEXT_ANTIALIAS_MODE_GRAYSCALE);
            if(FAILED(ui_target_->CreateSolidColorBrush(D2D1::ColorF(D2D1::ColorF::White),&ui_brush_))){
                error="Could not create the UI text brush.";return false;
            }
        }
        width_=width;height_=height;
        return create_frame_resources(current_render_scale_,error);
    }
    bool render(const World& world,std::string& error,const std::filesystem::path* capture_before_present){
        if(!ready()){error="D3D11 renderer is not ready.";return false;}
        const bool trace_capture=capture_before_present&&GetEnvironmentVariableA("TC_CAPTURE_TRACE",nullptr,0)>0;
        const auto capture_stage=[trace_capture](const char* stage){
            if(trace_capture)std::cerr<<"TC_CAPTURE_STAGE "<<stage<<'\n'<<std::flush;
        };
        capture_stage("render_begin");
        gpu_skinned_draws_=cpu_skinned_draws_=0;
        cpu_skin_wall_ms_=0.0F;
        skinning_error_.clear();
        inverse_bind_frame_cache_.clear();
        inverse_bind_reads_=inverse_bind_cache_hits_=0;
        submitted_geometry_draws_=submitted_shadow_draws_=0;
        resolve_gpu_timing(world.render_settings);
        if(world.render_settings.dynamic_resolution&&!dynamic_resolution_active_){
            adaptive_render_scale_=std::clamp(world.render_settings.render_scale,world.render_settings.minimum_render_scale,world.render_settings.maximum_render_scale);
        }
        dynamic_resolution_active_=world.render_settings.dynamic_resolution;
        temporal_enabled_=world.render_settings.upscaler!="native";
        const float requested_scale=dynamic_resolution_active_?adaptive_render_scale_:std::clamp(world.render_settings.render_scale,0.25F,1.0F);
        if(std::abs(requested_scale-current_render_scale_)>0.001F&&!create_frame_resources(requested_scale,error))return false;
        begin_gpu_timing();
        const WorldVector3 camera_world=active_camera(world);
        const WorldVector3 camera_target_world=active_camera_target(world);
        current_render_origin_=render_origin_for(camera_world,world.simulation_settings);
        if(!previous_render_origin_valid_)previous_render_origin_=current_render_origin_;
        const XMVECTOR eye=XMVectorSet(static_cast<float>(camera_world.x-current_render_origin_.x),
                                      static_cast<float>(camera_world.y-current_render_origin_.y),
                                      static_cast<float>(camera_world.z-current_render_origin_.z),world.render_settings.exposure);
        const XMVECTOR camera_target=XMVectorSet(static_cast<float>(camera_target_world.x-current_render_origin_.x),
                                                static_cast<float>(camera_target_world.y-current_render_origin_.y),
                                                static_cast<float>(camera_target_world.z-current_render_origin_.z),1);
        const XMMATRIX view=XMMatrixLookAtLH(eye,camera_target,XMVectorSet(0,1,0,0));
        XMMATRIX projection=XMMatrixPerspectiveFovLH(XMConvertToRadians(active_fov(world)),float(width_)/float(std::max(1,height_)),0.05F,5000);
        if(temporal_enabled_){
            const float jitter_x=halton(frame_index_+1,2)-0.5F,jitter_y=halton(frame_index_+1,3)-0.5F;
            projection.r[2]=XMVectorAdd(projection.r[2],XMVectorSet(jitter_x*2.0F/render_width_,-jitter_y*2.0F/render_height_,0,0));
        }
        const XMMATRIX view_projection=view*projection;
        current_sun_=active_sun(world);current_render_settings_=world.render_settings;build_dynamic_gi_sources(world);
        const XMVECTOR light_direction=XMVector3Normalize(XMVectorSet(current_sun_.direction.x,current_sun_.direction.y,current_sun_.direction.z,0));
        const XMVECTOR light_target=camera_target,light_position=XMVectorSubtract(light_target,XMVectorScale(light_direction,45.0F));
        const XMVECTOR world_up=std::abs(XMVectorGetY(light_direction))>0.98F?XMVectorSet(0,0,1,0):XMVectorSet(0,1,0,0);
        const XMMATRIX light_view=XMMatrixLookAtLH(light_position,light_target,world_up);
        const XMMATRIX light_projection=XMMatrixOrthographicLH(60,60,0.1F,100);
        const auto shadow_start=std::chrono::steady_clock::now();
        draw_shadow(world,light_view,light_view*light_projection);
        if(!skinning_error_.empty()){error=skinning_error_;return false;}
        shadow_wall_ms_=std::chrono::duration<float,std::milli>(std::chrono::steady_clock::now()-shadow_start).count();
        capture_stage("shadow_complete");
        const auto geometry_start=std::chrono::steady_clock::now();
        const float clear[]={world.render_settings.sky_color.x*world.render_settings.exposure,
                             world.render_settings.sky_color.y*world.render_settings.exposure,
                             world.render_settings.sky_color.z*world.render_settings.exposure,1};
        context_->ClearRenderTargetView(scene_target_.Get(),clear);
        const float clear_motion[]={0,0,0,0};context_->ClearRenderTargetView(motion_target_.Get(),clear_motion);
        context_->ClearDepthStencilView(depth_view_.Get(),D3D11_CLEAR_DEPTH|D3D11_CLEAR_STENCIL,1,0);
        D3D11_VIEWPORT viewport{0,0,float(render_width_),float(render_height_),0,1};context_->RSSetViewports(1,&viewport);
        if(world.render_settings.atmosphere_enabled){
            context_->OMSetRenderTargets(1,scene_target_.GetAddressOf(),nullptr);context_->IASetInputLayout(nullptr);context_->IASetPrimitiveTopology(D3D11_PRIMITIVE_TOPOLOGY_TRIANGLELIST);
            context_->VSSetShader(post_vertex_shader_.Get(),nullptr,0);context_->PSSetShader(atmosphere_shader_.Get(),nullptr,0);
            update_sky_constants(XMMatrixInverse(nullptr,view_projection),eye);context_->Draw(3,0);
        }
        ID3D11RenderTargetView* scene_targets[]={scene_target_.Get(),motion_target_.Get()};
        context_->OMSetRenderTargets(2,scene_targets,depth_view_.Get());
        bind_geometry();context_->VSSetShader(vertex_shader_.Get(),nullptr,0);context_->PSSetShader(pixel_shader_.Get(),nullptr,0);
        context_->PSSetShaderResources(0,1,shadow_srv_.GetAddressOf());context_->PSSetSamplers(0,1,shadow_sampler_.GetAddressOf());context_->PSSetSamplers(1,1,material_sampler_.GetAddressOf());
        for(const auto& [entity,material]:world.renderables){
            const auto transform=world.transforms.find(entity);
            if(transform==world.transforms.end())continue;
            GpuMesh* render_mesh=is_builtin_cube(world,material)?nullptr:imported_mesh(world,material.mesh_asset);
            XMVECTOR bounds_center{};float bounds_radius{};
            const float camera_aspect=float(width_)/float(std::max(1,height_));
            bool in_view=true;
            if(material.skin_binding.empty())in_view=render_mesh?
                (!render_sphere(transform->second,render_mesh,bounds_center,bounds_radius)||
                 sphere_intersects_camera_frustum(bounds_center,bounds_radius,view,active_fov(world),camera_aspect)):
                cube_intersects_camera_frustum(transform->second,view,active_fov(world),camera_aspect);
            if(!in_view){
                previous_transforms_[entity]=transform->second;
                continue;
            }
            const auto environment=reflection_environment(world,transform->second.position);
            current_environment_intensity_=environment.second;
            bind_skinning(world,material.skin_binding,render_mesh);
            if(!skinning_error_.empty()){error=skinning_error_;return false;}
            const UINT index_count=bind_geometry(render_mesh);
            ID3D11ShaderResourceView* maps[]={
                material_texture(world,material.base_color_texture,white_texture_.Get(),true),
                material_texture(world,material.normal_texture,normal_texture_.Get(),false),
                material_texture(world,material.roughness_texture,white_texture_.Get(),false),
                material_texture(world,material.metallic_texture,white_texture_.Get(),false),
                material_texture(world,material.emission_texture,black_texture_.Get(),true),
                material_texture(world,environment.first,black_texture_.Get(),true),
            };
            context_->PSSetShaderResources(1,6,maps);
            const auto previous=previous_transforms_.find(entity);
            const Transform& previous_transform=previous==previous_transforms_.end()?transform->second:previous->second;
            update_constants(transform->second,previous_transform,material,view_projection,
                             previous_view_projection_valid_?previous_view_projection_:view_projection,light_view*light_projection,eye);
            context_->DrawIndexed(index_count,0,0);
            ++submitted_geometry_draws_;
            unbind_skinning();
            previous_transforms_[entity]=transform->second;
        }
        capture_stage("geometry_complete");
        geometry_wall_ms_=std::chrono::duration<float,std::milli>(std::chrono::steady_clock::now()-geometry_start).count();
        const auto post_start=std::chrono::steady_clock::now();
        ID3D11ShaderResourceView* none[10]={};context_->PSSetShaderResources(0,10,none);
        const int write_history=1-history_index_;
        context_->OMSetRenderTargets(1,history_target_[write_history].GetAddressOf(),nullptr);
        D3D11_VIEWPORT output_viewport{0,0,float(width_),float(height_),0,1};context_->RSSetViewports(1,&output_viewport);
        context_->IASetInputLayout(nullptr);context_->IASetPrimitiveTopology(D3D11_PRIMITIVE_TOPOLOGY_TRIANGLELIST);
        context_->VSSetShader(post_vertex_shader_.Get(),nullptr,0);context_->PSSetShader(temporal_shader_.Get(),nullptr,0);
        update_post_constants(world.render_settings.sharpness);
        ID3D11ShaderResourceView* temporal_inputs[]={scene_resource_.Get(),motion_resource_.Get(),history_resource_[history_index_].Get()};
        context_->PSSetShaderResources(7,3,temporal_inputs);context_->Draw(3,0);
        context_->PSSetShaderResources(7,3,none);
        context_->OMSetRenderTargets(1,display_target_.GetAddressOf(),nullptr);
        context_->ClearRenderTargetView(display_target_.Get(),clear);
        context_->PSSetShader(display_shader_.Get(),nullptr,0);
        context_->PSSetShaderResources(9,1,history_resource_[write_history].GetAddressOf());context_->Draw(3,0);
        context_->PSSetShaderResources(9,1,none);
        ui_bitmap_ms_=ui_draw_ms_=ui_copy_ms_=ui_text_ms_=ui_blend_ms_=ui_upload_ms_=0.0F;
        if(!world.ui_widgets.empty()){
            capture_stage("ui_begin");
            if(!draw_ui(world,error))return false;
            capture_stage("ui_complete");
            context_->PSSetShader(ui_shader_.Get(),nullptr,0);
            context_->PSSetShaderResources(12,1,ui_resource_.GetAddressOf());
            context_->OMSetBlendState(ui_blend_state_.Get(),nullptr,0xFFFFFFFF);
            context_->Draw(3,0);
            context_->OMSetBlendState(nullptr,nullptr,0xFFFFFFFF);
            ID3D11ShaderResourceView* no_ui=nullptr;
            context_->PSSetShaderResources(12,1,&no_ui);
        }
        history_index_=write_history;history_valid_=true;previous_view_projection_=view_projection;previous_view_projection_valid_=true;
        post_wall_ms_=std::chrono::duration<float,std::milli>(std::chrono::steady_clock::now()-post_start).count();
        previous_render_origin_=current_render_origin_;previous_render_origin_valid_=true;
        context_->OMSetRenderTargets(0,nullptr,nullptr);
        end_gpu_timing();
        // The GPU work query ends before copying into the vsynced swap-chain buffer.
        // Wall-clock frame pacing separately measures the display synchronization.
        context_->CopyResource(back_buffer_.Get(),display_texture_.Get());
        capture_stage("back_buffer_copy_queued");
        if(capture_before_present&&!capture(*capture_before_present,error))return false;
        capture_stage("capture_complete");
        const auto present_start=std::chrono::steady_clock::now();
        const HRESULT present_status=swap_chain_->Present(vsync_?1:0,0);
        present_wall_ms_=std::chrono::duration<float,std::milli>(std::chrono::steady_clock::now()-present_start).count();
        if(timing_present_cursor_<gpu_timing_.size()){
            gpu_timing_[timing_present_cursor_].present_wall_ms=present_wall_ms_;
            gpu_timing_[timing_present_cursor_].vsync=vsync_;
            timing_present_cursor_=gpu_timing_.size();
        }
        capture_stage("present_complete");
        if(FAILED(present_status)){
            error="Could not present the rendered frame (HRESULT "+std::to_string(static_cast<unsigned long>(present_status))+"; device reason "+
                  std::to_string(static_cast<unsigned long>(device_->GetDeviceRemovedReason()))+").";
            return false;
        }
        ++frame_index_;error.clear();return true;
    }
    bool capture(const std::filesystem::path& path,std::string& error){
        if(!ready()){error="Cannot capture a frame before the D3D11 renderer is ready.";return false;}
        const bool trace_capture=GetEnvironmentVariableA("TC_CAPTURE_TRACE",nullptr,0)>0;
        const auto capture_stage=[trace_capture](const char* stage){
            if(trace_capture)std::cerr<<"TC_CAPTURE_STAGE "<<stage<<'\n'<<std::flush;
        };
        capture_stage("capture_begin");
        ComPtr<ID3D11Texture2D> back;
        if(FAILED(swap_chain_->GetBuffer(0,IID_PPV_ARGS(&back)))||!back){
            error="Could not acquire the GPU back buffer for capture.";return false;
        }
        D3D11_TEXTURE2D_DESC desc{};back->GetDesc(&desc);
        desc.Usage=D3D11_USAGE_STAGING;desc.BindFlags=0;desc.CPUAccessFlags=D3D11_CPU_ACCESS_READ;desc.MiscFlags=0;
        ComPtr<ID3D11Texture2D> staging;
        if(FAILED(device_->CreateTexture2D(&desc,nullptr,&staging))||!staging){
            error="Could not allocate the GPU capture staging texture.";return false;
        }
        context_->CopyResource(staging.Get(),back.Get());
        capture_stage("staging_copy_queued");
        context_->Flush();
        capture_stage("staging_flush_complete");
        D3D11_MAPPED_SUBRESOURCE mapped{};
        const auto deadline=std::chrono::steady_clock::now()+std::chrono::seconds(5);
        HRESULT map_status=DXGI_ERROR_WAS_STILL_DRAWING;
        do{
            map_status=context_->Map(staging.Get(),0,D3D11_MAP_READ,D3D11_MAP_FLAG_DO_NOT_WAIT,&mapped);
            if(map_status!=DXGI_ERROR_WAS_STILL_DRAWING)break;
            if(std::chrono::steady_clock::now()>=deadline){
                error="GPU capture readback timed out after 5 seconds (device reason "+
                    std::to_string(static_cast<unsigned long>(device_->GetDeviceRemovedReason()))+").";
                return false;
            }
            std::this_thread::sleep_for(std::chrono::milliseconds(1));
        }while(true);
        if(FAILED(map_status)){
            error="Could not read the GPU back buffer (HRESULT "+
                std::to_string(static_cast<unsigned long>(map_status))+"; device reason "+
                std::to_string(static_cast<unsigned long>(device_->GetDeviceRemovedReason()))+").";
            return false;
        }
        capture_stage("staging_map_complete");
        const DWORD row=(desc.Width*3+3)&~3U;
        std::vector<unsigned char> pixels(static_cast<std::size_t>(row)*desc.Height);
        for(UINT y=0;y<desc.Height;++y){
            const auto* source=static_cast<const unsigned char*>(mapped.pData)+(desc.Height-1-y)*mapped.RowPitch;
            auto* target=pixels.data()+y*row;
            for(UINT x=0;x<desc.Width;++x){
                target[x*3]=source[x*4];target[x*3+1]=source[x*4+1];target[x*3+2]=source[x*4+2];
            }
        }
        context_->Unmap(staging.Get(),0);
        capture_stage("pixels_copied");
        BITMAPFILEHEADER file{};BITMAPINFOHEADER info{};
        file.bfType=0x4D42;file.bfOffBits=sizeof(file)+sizeof(info);
        file.bfSize=file.bfOffBits+static_cast<DWORD>(pixels.size());
        info.biSize=sizeof(info);info.biWidth=static_cast<LONG>(desc.Width);
        info.biHeight=static_cast<LONG>(desc.Height);info.biPlanes=1;
        info.biBitCount=24;info.biCompression=BI_RGB;
        std::ofstream stream(path,std::ios::binary);
        if(!stream){error="Could not open the GPU capture destination.";return false;}
        stream.write(reinterpret_cast<char*>(&file),sizeof(file));
        stream.write(reinterpret_cast<char*>(&info),sizeof(info));
        stream.write(reinterpret_cast<char*>(pixels.data()),static_cast<std::streamsize>(pixels.size()));
        if(!stream){error="Could not write the GPU capture bitmap.";return false;}
        capture_stage("bitmap_written");
        error.clear();return true;
    }
    bool ready()const noexcept{return device_&&swap_chain_&&render_target_&&display_target_&&back_buffer_;}
    GpuRenderProfile profile()const noexcept{return {average_gpu_ms_,current_render_scale_,render_width_,render_height_,temporal_enabled_,dynamic_resolution_active_,gpu_skinned_draws_,cpu_skinned_draws_,submitted_geometry_draws_,submitted_shadow_draws_,resolved_gpu_samples_ms_,resolved_gpu_sample_count_,vsync_,gpu_skin_stream_cache_.size(),gpu_skin_cache_.size(),present_wall_ms_,cpu_skin_wall_ms_,shadow_wall_ms_,geometry_wall_ms_,post_wall_ms_,inverse_bind_reads_,inverse_bind_cache_hits_,ui_compositions_,ui_texture_creations_,ui_image_decodes_,ui_bitmap_ms_,ui_draw_ms_,ui_copy_ms_,ui_text_ms_,ui_blend_ms_,ui_upload_ms_,average_gpu_work_ms_,history_allocations_};}
    GpuAdapterInfo adapter_info()const{return adapter_info_;}
private:
    bool draw_ui(const World& world,std::string& error){
        if(!ui_target_||!ui_brush_){error="UI Document renderer is unavailable.";return false;}
        std::ostringstream key;
        key<<width_<<'x'<<height_<<'/'<<world.ui_canvas_width<<'x'<<world.ui_canvas_height
           <<"/scale="<<ui_scale_
           <<'/'<<world.ui_safe_left<<','<<world.ui_safe_top<<','
           <<world.ui_safe_right<<','<<world.ui_safe_bottom;
        for(const auto& widget:world.ui_widgets){
            key<<'\n'<<widget.id<<'\t'<<widget.type<<'\t'<<widget.x<<'\t'<<widget.y
               <<'\t'<<widget.width<<'\t'<<widget.height<<'\t'<<widget.focused
               <<'\t'<<widget.image_asset_id<<'\t'<<widget.text
               <<'\t'<<widget.accessible_name<<'\t'<<widget.parent_id
               <<'\t'<<widget.anchor_x<<'\t'<<widget.anchor_y
               <<'\t'<<widget.pivot_x<<'\t'<<widget.pivot_y
               <<'\t'<<widget.offset_x<<'\t'<<widget.offset_y
               <<'\t'<<widget.layout_width<<'\t'<<widget.layout_height
               <<'\t'<<widget.min_viewport_width;
            if(widget.type=="image"){
                const auto asset=world.assets.find(widget.image_asset_id);
                if(asset==world.assets.end()||asset->second.type!="texture"){
                    key<<"\tmissing-image-asset";
                }else{
                    key<<'\t'<<path_utf8(asset->second.source);
                    std::error_code file_error;
                    const auto modified=std::filesystem::last_write_time(asset->second.source,file_error);
                    if(file_error){key<<"\tmissing-image-file";continue;}
                    const auto size=std::filesystem::file_size(asset->second.source,file_error);
                    if(file_error){key<<"\tmissing-image-size";continue;}
                    key<<'\t'<<modified.time_since_epoch().count()<<'\t'<<size;
                }
            }
        }
        const std::string content_key=key.str();
        if(content_key==ui_content_key_&&ui_resource_)return true;
        const auto ui_probe_start=std::chrono::steady_clock::now();
        const auto layout=layout_ui_widgets(world,static_cast<float>(width_),static_cast<float>(height_),ui_scale_);
        ui_target_->BeginDraw();
        ui_target_->Clear(D2D1::ColorF(0.0F,0.0F,0.0F,0.0F));
        for(std::size_t index=0;index<world.ui_widgets.size();++index){
            const auto& widget=world.ui_widgets[index];
            const auto& bounds=layout[index];
            if(!bounds.visible)continue;
            const auto rect=D2D1::RectF(bounds.x,bounds.y,bounds.x+bounds.width,bounds.y+bounds.height);
            if(widget.type=="panel"||widget.type=="button"){
                ui_brush_->SetColor(widget.type=="button"?
                    (widget.focused?D2D1::ColorF(0.22F,0.62F,0.86F,0.98F):
                                    D2D1::ColorF(0.08F,0.38F,0.57F,0.88F)):
                    D2D1::ColorF(0.02F,0.08F,0.13F,0.72F));
                ui_target_->FillRoundedRectangle(D2D1::RoundedRect(rect,8.0F*ui_scale_,8.0F*ui_scale_),ui_brush_.Get());
            }
            if(widget.type=="image"){
                const auto asset=world.assets.find(widget.image_asset_id);
                if(asset==world.assets.end()||asset->second.type!="texture"){
                    ui_target_->EndDraw();
                    error="UI image has no packaged texture asset: "+widget.image_asset_id;return false;
                }
                const auto image_key=asset->second.source.wstring();
                std::error_code file_error;
                const auto modified=std::filesystem::last_write_time(asset->second.source,file_error);
                if(file_error){
                    ui_target_->EndDraw();
                    error="Could not stat UI image: "+path_utf8(asset->second.source);return false;
                }
                const auto size=std::filesystem::file_size(asset->second.source,file_error);
                if(file_error){
                    ui_target_->EndDraw();
                    error="Could not stat UI image: "+path_utf8(asset->second.source);return false;
                }
                auto& cached=ui_image_cache_[image_key];
                if(!cached.decoded||cached.modified!=modified||cached.size!=size){
                    ComPtr<IWICBitmapDecoder> decoder;
                    ComPtr<IWICBitmapFrameDecode> frame;
                    ComPtr<IWICFormatConverter> converter;
                    ComPtr<IWICBitmap> decoded;
                    if(FAILED(wic_->CreateDecoderFromFilename(asset->second.source.c_str(),nullptr,GENERIC_READ,
                        WICDecodeMetadataCacheOnLoad,&decoder))||FAILED(decoder->GetFrame(0,&frame))||
                       FAILED(wic_->CreateFormatConverter(&converter))||
                       FAILED(converter->Initialize(frame.Get(),GUID_WICPixelFormat32bppPBGRA,
                           WICBitmapDitherTypeNone,nullptr,0.0,WICBitmapPaletteTypeCustom))||
                       FAILED(wic_->CreateBitmapFromSource(converter.Get(),WICBitmapCacheOnLoad,&decoded))){
                        ui_target_->EndDraw();
                        error="Could not decode UI image: "+path_utf8(asset->second.source);return false;
                    }
                    cached.decoded=std::move(decoded);
                    cached.bitmap.Reset();
                    cached.modified=modified;
                    cached.size=size;
                    ++ui_image_decodes_;
                }
                if(!cached.bitmap&&FAILED(ui_target_->CreateBitmapFromWicBitmap(cached.decoded.Get(),nullptr,&cached.bitmap))){
                    ui_target_->EndDraw();
                    error="Could not create UI bitmap: "+path_utf8(asset->second.source);return false;
                }
                ui_target_->DrawBitmap(cached.bitmap.Get(),rect,1.0F,D2D1_BITMAP_INTERPOLATION_MODE_LINEAR);
            }
        }
        if(FAILED(ui_target_->EndDraw())){error="UI Document draw failed.";return false;}
        const auto ui_probe_draw=std::chrono::steady_clock::now();
        ui_pixels_.resize(static_cast<std::size_t>(width_)*height_*4U);
        if(FAILED(ui_bitmap_->CopyPixels(nullptr,static_cast<UINT>(width_*4),
                                         static_cast<UINT>(ui_pixels_.size()),ui_pixels_.data()))){
            error="Could not read the UI bitmap.";return false;
        }
        const auto ui_probe_bitmap=std::chrono::steady_clock::now();
        HDC text_dc=CreateCompatibleDC(nullptr);
        BITMAPINFO text_info{};
        text_info.bmiHeader.biSize=sizeof(BITMAPINFOHEADER);
        text_info.bmiHeader.biWidth=width_;
        text_info.bmiHeader.biHeight=-height_;
        text_info.bmiHeader.biPlanes=1;
        text_info.bmiHeader.biBitCount=32;
        text_info.bmiHeader.biCompression=BI_RGB;
        void* text_bits=nullptr;
        HBITMAP text_bitmap=text_dc?CreateDIBSection(text_dc,&text_info,DIB_RGB_COLORS,&text_bits,nullptr,0):nullptr;
        HFONT text_font=CreateFontW(-static_cast<int>(std::lround(22.0F*ui_scale_)),0,0,0,FW_NORMAL,FALSE,FALSE,FALSE,DEFAULT_CHARSET,
                                   OUT_DEFAULT_PRECIS,CLIP_DEFAULT_PRECIS,ANTIALIASED_QUALITY,
                                   DEFAULT_PITCH|FF_DONTCARE,L"Segoe UI");
        if(!text_dc||!text_bitmap||!text_bits||!text_font){
            if(text_font)DeleteObject(text_font);
            if(text_bitmap)DeleteObject(text_bitmap);
            if(text_dc)DeleteDC(text_dc);
            error="Could not rasterize UI text.";return false;
        }
        std::memset(text_bits,0,ui_pixels_.size());
        HGDIOBJ old_bitmap=SelectObject(text_dc,text_bitmap);
        HGDIOBJ old_font=SelectObject(text_dc,text_font);
        SetBkMode(text_dc,TRANSPARENT);
        SetTextColor(text_dc,RGB(255,255,255));
        LONG text_min_x=width_,text_min_y=height_,text_max_x=0,text_max_y=0;
        for(std::size_t index=0;index<world.ui_widgets.size();++index){
            const auto& widget=world.ui_widgets[index];
            if(!layout[index].visible)continue;
            if(widget.type=="image")continue;
            const auto& label=widget.text;
            if(label.empty())continue;
            const int length=MultiByteToWideChar(CP_UTF8,MB_ERR_INVALID_CHARS,label.c_str(),
                                                 static_cast<int>(label.size()),nullptr,0);
            if(length<=0)continue;
            std::wstring wide(static_cast<std::size_t>(length),L'\0');
            MultiByteToWideChar(CP_UTF8,MB_ERR_INVALID_CHARS,label.c_str(),
                                static_cast<int>(label.size()),wide.data(),length);
            const auto& bounds=layout[index];
            RECT rect{static_cast<LONG>(std::lround(bounds.x)),
                      static_cast<LONG>(std::lround(bounds.y)),
                      static_cast<LONG>(std::lround(bounds.x+bounds.width)),
                      static_cast<LONG>(std::lround(bounds.y+bounds.height))};
            DrawTextW(text_dc,wide.c_str(),length,&rect,DT_LEFT|DT_TOP|DT_WORDBREAK|DT_NOPREFIX);
            text_min_x=std::min(text_min_x,std::clamp(rect.left,0L,static_cast<LONG>(width_)));
            text_min_y=std::min(text_min_y,std::clamp(rect.top,0L,static_cast<LONG>(height_)));
            text_max_x=std::max(text_max_x,std::clamp(rect.right,0L,static_cast<LONG>(width_)));
            text_max_y=std::max(text_max_y,std::clamp(rect.bottom,0L,static_cast<LONG>(height_)));
        }
        if(!GdiFlush()){
            SelectObject(text_dc,old_font);
            SelectObject(text_dc,old_bitmap);
            DeleteObject(text_font);
            DeleteObject(text_bitmap);
            DeleteDC(text_dc);
            error="Could not complete UI text rasterization.";return false;
        }
        const auto ui_probe_gdi=std::chrono::steady_clock::now();
        const auto* glyphs=static_cast<const std::uint8_t*>(text_bits);
        for(LONG y=text_min_y;y<text_max_y;++y){
            for(LONG x=text_min_x;x<text_max_x;++x){
                const auto offset=(static_cast<std::size_t>(y)*width_+x)*4U;
                const unsigned alpha=std::max({glyphs[offset],glyphs[offset+1],glyphs[offset+2]});
                if(alpha==0U)continue;
                const unsigned inverse=255U-alpha;
                ui_pixels_[offset]=static_cast<std::uint8_t>((255U*alpha+ui_pixels_[offset]*inverse+127U)/255U);
                ui_pixels_[offset+1]=static_cast<std::uint8_t>((247U*alpha+ui_pixels_[offset+1]*inverse+127U)/255U);
                ui_pixels_[offset+2]=static_cast<std::uint8_t>((240U*alpha+ui_pixels_[offset+2]*inverse+127U)/255U);
                ui_pixels_[offset+3]=static_cast<std::uint8_t>(alpha+(ui_pixels_[offset+3]*inverse+127U)/255U);
            }
        }
        SelectObject(text_dc,old_font);
        SelectObject(text_dc,old_bitmap);
        DeleteObject(text_font);
        DeleteObject(text_bitmap);
        DeleteDC(text_dc);
        const auto ui_probe_blend=std::chrono::steady_clock::now();
        D3D11_TEXTURE2D_DESC texture_desc{};
        texture_desc.Width=static_cast<UINT>(width_);texture_desc.Height=static_cast<UINT>(height_);
        texture_desc.MipLevels=texture_desc.ArraySize=1;
        texture_desc.Format=DXGI_FORMAT_B8G8R8A8_UNORM;
        texture_desc.SampleDesc.Count=1;texture_desc.Usage=D3D11_USAGE_DEFAULT;
        texture_desc.BindFlags=D3D11_BIND_SHADER_RESOURCE;
        if(!ui_texture_||!ui_resource_){
            ComPtr<ID3D11Texture2D> next_texture;
            ComPtr<ID3D11ShaderResourceView> next_resource;
            if(FAILED(device_->CreateTexture2D(&texture_desc,nullptr,&next_texture))||
               FAILED(device_->CreateShaderResourceView(next_texture.Get(),nullptr,&next_resource))){
                error="Could not create the UI composition texture.";return false;
            }
            ui_texture_=std::move(next_texture);
            ui_resource_=std::move(next_resource);
            ++ui_texture_creations_;
        }
        context_->UpdateSubresource(ui_texture_.Get(),0,nullptr,ui_pixels_.data(),static_cast<UINT>(width_*4),0);
        const auto ui_probe_end=std::chrono::steady_clock::now();
        const auto elapsed=[](auto start,auto end){return std::chrono::duration<float,std::milli>(end-start).count();};
        ui_bitmap_ms_=elapsed(ui_probe_start,ui_probe_bitmap);
        ui_draw_ms_=elapsed(ui_probe_start,ui_probe_draw);
        ui_copy_ms_=elapsed(ui_probe_draw,ui_probe_bitmap);
        ui_text_ms_=elapsed(ui_probe_bitmap,ui_probe_gdi);
        ui_blend_ms_=elapsed(ui_probe_gdi,ui_probe_blend);
        ui_upload_ms_=elapsed(ui_probe_blend,ui_probe_end);
        ++ui_compositions_;
        ui_content_key_=content_key;
        return true;
    }
    struct CpuSkinFrame{std::vector<Vertex> vertices;std::vector<XMFLOAT3> skinned_positions;std::vector<std::uint8_t> has_skin;ComPtr<ID3D11Buffer> gpu_vertices;std::uint64_t frame{std::numeric_limits<std::uint64_t>::max()};std::uint64_t gpu_frame{std::numeric_limits<std::uint64_t>::max()};};
    struct GpuMesh{ComPtr<ID3D11Buffer> vertices;ComPtr<ID3D11Buffer> indices;UINT index_count{};std::vector<Vertex> source_vertices;std::vector<std::uint32_t> source_position_indices;XMFLOAT3 bounds_center{};float bounds_radius{};bool bounds_valid{false};std::uint64_t skin_frame{std::numeric_limits<std::uint64_t>::max()};std::string skin_binding_id;bool cpu_skin_active{false};std::unordered_map<std::string,CpuSkinFrame> cpu_skin_frames;};
    struct CpuSkinData{std::vector<XMFLOAT3> rest_positions;std::vector<std::uint32_t> offsets,joint_indices;std::vector<float> weights;bool valid{false};};
    struct GpuSkinData{ComPtr<ID3D11Buffer> vertices,palette,influences;ComPtr<ID3D11ShaderResourceView> vertex_srv,palette_srv,influence_srv;std::size_t joint_count{};std::uint64_t frame{std::numeric_limits<std::uint64_t>::max()};bool valid{false};};
    struct GpuSkinStreams{ComPtr<ID3D11Buffer> vertices,influences;ComPtr<ID3D11ShaderResourceView> vertex_srv,influence_srv;};
    struct GpuTimingFrame{ComPtr<ID3D11Query> disjoint,start,end;bool pending{false},vsync{true};float present_wall_ms{0.0F};};
    static float halton(std::uint64_t index,std::uint32_t base){float result=0,fraction=1.0F;while(index){fraction/=base;result+=fraction*(index%base);index/=base;}return result;}
    GpuMesh* imported_mesh(const World& world,const std::string& id){
        if(id.empty())return nullptr;
        if(const auto found=mesh_cache_.find(id);found!=mesh_cache_.end())return &found->second;
        const auto asset=world.assets.find(id);if(asset==world.assets.end()||asset->second.source.extension()!=L".obj")return nullptr;
        std::ifstream stream(asset->second.source);if(!stream)return nullptr;
        std::vector<XMFLOAT3> positions,normals;std::vector<XMFLOAT2> uvs;std::vector<Vertex> output;std::vector<std::uint32_t> output_indices,source_position_indices;std::string line;
        auto resolve=[](int index,std::size_t count)->std::size_t{return index>0?static_cast<std::size_t>(index-1):static_cast<std::size_t>(static_cast<int>(count)+index);};
        while(std::getline(stream,line)){std::istringstream row(line);std::string type;row>>type;
            if(type=="v"){XMFLOAT3 value{};row>>value.x>>value.y>>value.z;positions.push_back(value);}
            else if(type=="vn"){XMFLOAT3 value{};row>>value.x>>value.y>>value.z;normals.push_back(value);}
            else if(type=="vt"){XMFLOAT2 value{};row>>value.x>>value.y;value.y=1.0F-value.y;uvs.push_back(value);}
            else if(type=="f"){std::vector<std::pair<Vertex,std::uint32_t>> face;std::string token;while(row>>token){std::replace(token.begin(),token.end(),'/',' ');std::istringstream values(token);int p=0,t=0,n=0;values>>p;if(!values.eof())values>>t;if(!values.eof())values>>n;const auto position_index=p==0?positions.size():resolve(p,positions.size());if(position_index>=positions.size())continue;Vertex vertex{};vertex.position=positions[position_index];vertex.uv=t!=0&&resolve(t,uvs.size())<uvs.size()?uvs[resolve(t,uvs.size())]:XMFLOAT2{};vertex.normal=n!=0&&resolve(n,normals.size())<normals.size()?normals[resolve(n,normals.size())]:XMFLOAT3{0,1,0};face.push_back({vertex,static_cast<std::uint32_t>(position_index)});}for(std::size_t corner=1;corner+1<face.size();++corner){for(const auto index:{std::size_t(0),corner,corner+1}){output_indices.push_back(static_cast<std::uint32_t>(output.size()));output.push_back(face[index].first);source_position_indices.push_back(face[index].second);}}}
        }
        if(output.empty()||output_indices.empty()||output.size()>10000000)return nullptr;
        GpuMesh mesh;
        XMFLOAT3 low{std::numeric_limits<float>::max(),std::numeric_limits<float>::max(),std::numeric_limits<float>::max()};
        XMFLOAT3 high{std::numeric_limits<float>::lowest(),std::numeric_limits<float>::lowest(),std::numeric_limits<float>::lowest()};
        bool finite_vertices=true;
        for(const auto& vertex:output){
            const auto& point=vertex.position;
            finite_vertices=finite_vertices&&std::isfinite(point.x)&&std::isfinite(point.y)&&std::isfinite(point.z);
            if(!finite_vertices)break;
            low.x=std::min(low.x,point.x);low.y=std::min(low.y,point.y);low.z=std::min(low.z,point.z);
            high.x=std::max(high.x,point.x);high.y=std::max(high.y,point.y);high.z=std::max(high.z,point.z);
        }
        if(finite_vertices){
            const double cx=(double(low.x)+double(high.x))*0.5,cy=(double(low.y)+double(high.y))*0.5,cz=(double(low.z)+double(high.z))*0.5;
            if(std::abs(cx)<=std::numeric_limits<float>::max()&&
               std::abs(cy)<=std::numeric_limits<float>::max()&&
               std::abs(cz)<=std::numeric_limits<float>::max()){
                mesh.bounds_center={float(cx),float(cy),float(cz)};
                double radius_squared=0;
                for(const auto& vertex:output){
                    const double dx=double(vertex.position.x)-mesh.bounds_center.x;
                    const double dy=double(vertex.position.y)-mesh.bounds_center.y;
                    const double dz=double(vertex.position.z)-mesh.bounds_center.z;
                    radius_squared=std::max(radius_squared,dx*dx+dy*dy+dz*dz);
                }
                const double radius=std::sqrt(radius_squared);
                if(radius<std::numeric_limits<float>::max()){
                    mesh.bounds_radius=std::nextafter(float(radius),std::numeric_limits<float>::infinity());
                    mesh.bounds_valid=std::isfinite(mesh.bounds_radius);
                }
            }
        }
        D3D11_BUFFER_DESC desc{};desc.Usage=D3D11_USAGE_DYNAMIC;desc.CPUAccessFlags=D3D11_CPU_ACCESS_WRITE;desc.BindFlags=D3D11_BIND_VERTEX_BUFFER;desc.ByteWidth=static_cast<UINT>(output.size()*sizeof(Vertex));D3D11_SUBRESOURCE_DATA data{output.data()};if(FAILED(device_->CreateBuffer(&desc,&data,&mesh.vertices)))return nullptr;desc.Usage=D3D11_USAGE_IMMUTABLE;desc.CPUAccessFlags=0;desc.BindFlags=D3D11_BIND_INDEX_BUFFER;desc.ByteWidth=static_cast<UINT>(output_indices.size()*sizeof(std::uint32_t));data.pSysMem=output_indices.data();if(FAILED(device_->CreateBuffer(&desc,&data,&mesh.indices)))return nullptr;mesh.index_count=static_cast<UINT>(output_indices.size());mesh.source_vertices=std::move(output);mesh.source_position_indices=std::move(source_position_indices);mesh_cache_[id]=std::move(mesh);return &mesh_cache_[id];
    }
    template<typename Value>static bool read_binary(const std::filesystem::path& path,std::size_t count,std::vector<Value>& output){if(count>320000000U)return false;std::ifstream stream(path,std::ios::binary|std::ios::ate);if(!stream)return false;const auto size=stream.tellg();if(size<0||static_cast<std::uint64_t>(size)<count*sizeof(Value))return false;stream.seekg(0);output.resize(count);stream.read(reinterpret_cast<char*>(output.data()),static_cast<std::streamsize>(count*sizeof(Value)));return bool(stream);}
    bool build_skin_matrix_palette(const World& world,const std::string& skin_id,std::vector<Matrix4>& palette,std::string& error){
        palette.clear();
        const auto skin=world.skin_bindings.find(skin_id);
        if(skin==world.skin_bindings.end()){error="Unknown skin binding: "+skin_id;return false;}
        if(skin->second.joint_ids.size()>65535U){error="Skin palette exceeds the native joint limit.";return false;}
        const auto asset=world.assets.find(skin->second.inverse_bind_asset);
        if(asset==world.assets.end()){error="Inverse-bind asset is unavailable: "+skin->second.inverse_bind_asset;return false;}
        const std::size_t float_count=skin->second.joint_ids.size()*16U;
        const std::string key=skin->second.inverse_bind_asset+"\x1f"+std::to_string(float_count);
        auto found=inverse_bind_frame_cache_.find(key);
        if(found==inverse_bind_frame_cache_.end()){
            std::vector<float> values;
            if(!read_binary(asset->second.source,float_count,values)){error="Could not read inverse-bind asset: "+path_utf8(asset->second.source);return false;}
            found=inverse_bind_frame_cache_.emplace(key,std::move(values)).first;
            ++inverse_bind_reads_;
        }else{
            ++inverse_bind_cache_hits_;
        }
        return tc::runtime::build_skin_matrix_palette_from_values(world,skin_id,found->second,palette,error);
    }
    static std::string skin_source_key(const SkinBinding& skin){
        return std::to_string(skin.vertex_count)+"\x1f"+std::to_string(skin.maximum_influences)+"\x1f"+
               skin.rest_positions_asset+"\x1f"+skin.influence_offsets_asset+"\x1f"+
               skin.joint_indices_asset+"\x1f"+skin.weights_asset;
    }
    CpuSkinData& cpu_skin_data(const World& world,const SkinBinding& skin){
        const std::string key=skin_source_key(skin);
        if(const auto found=cpu_skin_cache_.find(key);found!=cpu_skin_cache_.end())return found->second;CpuSkinData data;const auto asset_path=[&world](const std::string& id){const auto found=world.assets.find(id);return found==world.assets.end()?std::filesystem::path{}:found->second.source;};
        std::vector<float> rest;if(!read_binary(asset_path(skin.rest_positions_asset),skin.vertex_count*3U,rest)||!read_binary(asset_path(skin.influence_offsets_asset),skin.vertex_count+1U,data.offsets)){cpu_skin_cache_[key]=std::move(data);return cpu_skin_cache_[key];}
        const std::size_t influence_count=data.offsets.empty()?0U:static_cast<std::size_t>(data.offsets.back());if(influence_count>skin.vertex_count*std::max<std::size_t>(1U,skin.maximum_influences)||!read_binary(asset_path(skin.joint_indices_asset),influence_count,data.joint_indices)||!read_binary(asset_path(skin.weights_asset),influence_count,data.weights)){cpu_skin_cache_[key]=std::move(data);return cpu_skin_cache_[key];}
        data.valid=detail::valid_skin_source(skin.vertex_count,skin.maximum_influences,
                                             skin.joint_ids.size(),rest,data.offsets,
                                             data.joint_indices,data.weights);
        if(data.valid){
            data.rest_positions.resize(skin.vertex_count);
            for(std::size_t index=0;index<skin.vertex_count;++index)
                data.rest_positions[index]={rest[index*3],rest[index*3+1],rest[index*3+2]};
        }
        cpu_skin_cache_[key]=std::move(data);return cpu_skin_cache_[key];
    }
    bool update_skinned_mesh(const World& world,const std::string& skin_id,GpuMesh& mesh){
        struct SkinTimer{float& total;std::chrono::steady_clock::time_point start{std::chrono::steady_clock::now()};~SkinTimer(){total+=std::chrono::duration<float,std::milli>(std::chrono::steady_clock::now()-start).count();}} timer{cpu_skin_wall_ms_};
        if(const auto cached=mesh.cpu_skin_frames.find(skin_id);
           cached!=mesh.cpu_skin_frames.end()&&cached->second.gpu_vertices&&cached->second.gpu_frame==frame_index_){
            mesh.skin_frame=frame_index_;mesh.skin_binding_id=skin_id;return true;
        }
        if(mesh.skin_frame==frame_index_&&mesh.skin_binding_id==skin_id)return true;
        const std::vector<Vertex>* upload=nullptr;
        std::vector<Vertex> fresh;
        if(const auto cached=mesh.cpu_skin_frames.find(skin_id);
           cached!=mesh.cpu_skin_frames.end()&&cached->second.frame==frame_index_)
            upload=&cached->second.vertices;
        if(!upload){
            const auto skin_found=world.skin_bindings.find(skin_id);if(skin_found==world.skin_bindings.end())return false;auto& data=cpu_skin_data(world,skin_found->second);if(!data.valid||mesh.source_vertices.size()!=mesh.source_position_indices.size())return false;std::vector<Matrix4> palette;std::string error;if(!build_skin_matrix_palette(world,skin_id,palette,error))return false;
            constexpr std::size_t cache_budget=64U*1024U*1024U;
            const std::size_t next_count=mesh.cpu_skin_frames.size()+1U;
            const bool cache_this=mesh.cpu_skin_frames.contains(skin_id)||
                (next_count<=8U&&mesh.source_vertices.size()<=cache_budget/(sizeof(Vertex)*2U*next_count));
            auto* deformed=&fresh;
            CpuSkinFrame* cache=nullptr;
            if(cache_this){cache=&mesh.cpu_skin_frames[skin_id];deformed=&cache->vertices;}
            // Mesh source vertices are immutable after upload. A cached entry
            // already retains every unskinned corner at rest; only the
            // influenced positions need refreshing on subsequent frames.
            if(!cache||deformed->empty())*deformed=mesh.source_vertices;
            // OBJ face corners duplicate source positions. Skin each source
            // position once, then scatter to render vertices.
            std::vector<XMFLOAT3> fresh_positions;
            std::vector<std::uint8_t> fresh_has_skin;
            auto& skinned_positions=cache?cache->skinned_positions:fresh_positions;
            auto& has_skin=cache?cache->has_skin:fresh_has_skin;
            skinned_positions.resize(data.rest_positions.size());
            has_skin.assign(data.rest_positions.size(),0);
            for(std::size_t source_index=0;source_index<data.rest_positions.size();++source_index){const auto& point=data.rest_positions[source_index];XMFLOAT3 position{};double total=0.0;for(std::size_t influence=data.offsets[source_index];influence<data.offsets[source_index+1];++influence){const auto joint=data.joint_indices[influence];if(joint>=palette.size())return false;const double weight=data.weights[influence];const auto& matrix=palette[joint];position.x+=static_cast<float>((point.x*matrix[0]+point.y*matrix[4]+point.z*matrix[8]+matrix[12])*weight);position.y+=static_cast<float>((point.x*matrix[1]+point.y*matrix[5]+point.z*matrix[9]+matrix[13])*weight);position.z+=static_cast<float>((point.x*matrix[2]+point.y*matrix[6]+point.z*matrix[10]+matrix[14])*weight);total+=weight;}if(total>1.0e-8){position.x/=static_cast<float>(total);position.y/=static_cast<float>(total);position.z/=static_cast<float>(total);skinned_positions[source_index]=position;has_skin[source_index]=1;}}
            for(std::size_t render_index=0;render_index<deformed->size();++render_index){const std::size_t source_index=mesh.source_position_indices[render_index];if(source_index>=skinned_positions.size())return false;if(has_skin[source_index])(*deformed)[render_index].position=skinned_positions[source_index];}
            if(cache)cache->frame=frame_index_;
            upload=deformed;
        }
        ID3D11Buffer* target=mesh.vertices.Get();
        if(auto cached=mesh.cpu_skin_frames.find(skin_id);cached!=mesh.cpu_skin_frames.end()){
            auto& entry=cached->second;
            if(!entry.gpu_vertices){D3D11_BUFFER_DESC desc{};mesh.vertices->GetDesc(&desc);device_->CreateBuffer(&desc,nullptr,&entry.gpu_vertices);}
            if(entry.gpu_vertices)target=entry.gpu_vertices.Get();
        }
        D3D11_MAPPED_SUBRESOURCE mapped{};if(FAILED(context_->Map(target,0,D3D11_MAP_WRITE_DISCARD,0,&mapped)))return false;std::memcpy(mapped.pData,upload->data(),upload->size()*sizeof(Vertex));context_->Unmap(target,0);
        if(target!=mesh.vertices.Get())mesh.cpu_skin_frames[skin_id].gpu_frame=frame_index_;
        mesh.skin_frame=frame_index_;mesh.skin_binding_id=skin_id;return true;
    }
    template<typename Value>bool create_structured_buffer(const std::vector<Value>& values,bool dynamic,ComPtr<ID3D11Buffer>& buffer,ComPtr<ID3D11ShaderResourceView>& view){if(values.empty()||values.size()>10000000U)return false;D3D11_BUFFER_DESC desc{};desc.ByteWidth=static_cast<UINT>(values.size()*sizeof(Value));desc.Usage=dynamic?D3D11_USAGE_DYNAMIC:D3D11_USAGE_IMMUTABLE;desc.CPUAccessFlags=dynamic?D3D11_CPU_ACCESS_WRITE:0;desc.BindFlags=D3D11_BIND_SHADER_RESOURCE;desc.MiscFlags=D3D11_RESOURCE_MISC_BUFFER_STRUCTURED;desc.StructureByteStride=sizeof(Value);D3D11_SUBRESOURCE_DATA initial{values.data()};if(FAILED(device_->CreateBuffer(&desc,dynamic?nullptr:&initial,&buffer)))return false;D3D11_SHADER_RESOURCE_VIEW_DESC srv{};srv.Format=DXGI_FORMAT_UNKNOWN;srv.ViewDimension=D3D11_SRV_DIMENSION_BUFFER;srv.Buffer.NumElements=static_cast<UINT>(values.size());return SUCCEEDED(device_->CreateShaderResourceView(buffer.Get(),&srv,&view));}
    GpuSkinData& gpu_skin_data(const World& world,const std::string& skin_id,GpuMesh& mesh){
        const std::string key=skin_id+":"+std::to_string(reinterpret_cast<std::uintptr_t>(&mesh));
        if(const auto found=gpu_skin_cache_.find(key);found!=gpu_skin_cache_.end())return found->second;
        GpuSkinData gpu;
        const auto skin_found=world.skin_bindings.find(skin_id);
        if(skin_found==world.skin_bindings.end()||skin_found->second.maximum_influences>32U){
            gpu_skin_cache_[key]=std::move(gpu);return gpu_skin_cache_[key];
        }
        auto& cpu=cpu_skin_data(world,skin_found->second);
        if(!cpu.valid||mesh.source_position_indices.size()!=mesh.source_vertices.size()||
           std::any_of(cpu.joint_indices.begin(),cpu.joint_indices.end(),
                       [&skin=skin_found->second](std::uint32_t joint){return joint>=skin.joint_ids.size();})){
            gpu_skin_cache_[key]=std::move(gpu);return gpu_skin_cache_[key];
        }
        const std::string stream_key=std::to_string(reinterpret_cast<std::uintptr_t>(&mesh))+"\x1f"+
                                     skin_source_key(skin_found->second);
        auto streams=gpu_skin_stream_cache_.find(stream_key);
        if(streams==gpu_skin_stream_cache_.end()){
            std::vector<GpuSkinVertex> vertices_data(mesh.source_vertices.size());
            std::vector<GpuSkinInfluence> influences_data;
            for(std::size_t render_index=0;render_index<vertices_data.size();++render_index){
                const std::size_t source=mesh.source_position_indices[render_index];
                if(source>=cpu.rest_positions.size()){
                    gpu_skin_cache_[key]=std::move(gpu);return gpu_skin_cache_[key];
                }
                auto& target=vertices_data[render_index];
                target.rest_position={cpu.rest_positions[source].x,cpu.rest_positions[source].y,cpu.rest_positions[source].z,1};
                const auto begin=cpu.offsets[source],end=cpu.offsets[source+1];
                if(end-begin>32U){
                    gpu_skin_cache_[key]=std::move(gpu);return gpu_skin_cache_[key];
                }
                target.metadata.x=end-begin;
                target.metadata.y=static_cast<std::uint32_t>(influences_data.size());
                for(std::uint32_t influence=begin;influence<end;++influence){
                    influences_data.push_back({cpu.joint_indices[influence],cpu.weights[influence]});
                }
            }
            if(influences_data.empty())influences_data.push_back({});
            GpuSkinStreams created;
            if(!create_structured_buffer(vertices_data,false,created.vertices,created.vertex_srv)||
               !create_structured_buffer(influences_data,false,created.influences,created.influence_srv)){
                gpu_skin_cache_[key]=std::move(gpu);return gpu_skin_cache_[key];
            }
            streams=gpu_skin_stream_cache_.emplace(stream_key,std::move(created)).first;
        }
        gpu.vertices=streams->second.vertices;gpu.vertex_srv=streams->second.vertex_srv;
        gpu.influences=streams->second.influences;gpu.influence_srv=streams->second.influence_srv;
        std::vector<XMFLOAT4X4> empty_palette(skin_found->second.joint_ids.size());
        if(!create_structured_buffer(empty_palette,true,gpu.palette,gpu.palette_srv)){
            gpu_skin_cache_[key]=std::move(gpu);return gpu_skin_cache_[key];
        }
        gpu.joint_count=empty_palette.size();gpu.valid=true;
        gpu_skin_cache_[key]=std::move(gpu);return gpu_skin_cache_[key];
    }
    bool bind_skinning(const World& world,const std::string& skin_id,GpuMesh* mesh){SkinConstants constants{};if(mesh)mesh->cpu_skin_active=false;if(mesh&&!skin_id.empty()){if(!cpu_skinning_diagnostic_){auto& gpu=gpu_skin_data(world,skin_id,*mesh);if(gpu.valid){if(gpu.frame!=frame_index_){std::vector<Matrix4> palette;std::string error;if(build_skin_matrix_palette(world,skin_id,palette,error)&&palette.size()==gpu.joint_count){D3D11_MAPPED_SUBRESOURCE mapped{};if(SUCCEEDED(context_->Map(gpu.palette.Get(),0,D3D11_MAP_WRITE_DISCARD,0,&mapped))){auto* output=static_cast<XMFLOAT4X4*>(mapped.pData);for(std::size_t index=0;index<palette.size();++index){auto* values=reinterpret_cast<float*>(&output[index]);for(std::size_t row=0;row<4;++row)for(std::size_t column=0;column<4;++column)values[column*4+row]=static_cast<float>(palette[index][row*4+column]);}context_->Unmap(gpu.palette.Get(),0);gpu.frame=frame_index_;}}}if(gpu.frame==frame_index_){ID3D11ShaderResourceView* resources[]={gpu.vertex_srv.Get(),gpu.palette_srv.Get(),gpu.influence_srv.Get()};context_->VSSetShaderResources(10,3,resources);constants.enabled=1;++gpu_skinned_draws_;}}}if(constants.enabled==0&&update_skinned_mesh(world,skin_id,*mesh)){mesh->cpu_skin_active=true;++cpu_skinned_draws_;}}
        if(!skin_id.empty()&&(!mesh||(constants.enabled==0&&!mesh->cpu_skin_active)))
            skinning_error_="Could not render skin binding: "+skin_id;
        D3D11_MAPPED_SUBRESOURCE mapped{};
        if(SUCCEEDED(context_->Map(skin_constants_.Get(),0,D3D11_MAP_WRITE_DISCARD,0,&mapped))){
            std::memcpy(mapped.pData,&constants,sizeof(constants));
            context_->Unmap(skin_constants_.Get(),0);
        }else skinning_error_="Could not update D3D11 skinning constants.";
        context_->VSSetConstantBuffers(3,1,skin_constants_.GetAddressOf());return constants.enabled!=0;}
    void unbind_skinning(){ID3D11ShaderResourceView* none[3]={};context_->VSSetShaderResources(10,3,none);}
    void create_solid(std::uint32_t rgba,ComPtr<ID3D11ShaderResourceView>& output){D3D11_TEXTURE2D_DESC desc{};desc.Width=desc.Height=1;desc.MipLevels=desc.ArraySize=1;desc.Format=DXGI_FORMAT_R8G8B8A8_UNORM;desc.SampleDesc.Count=1;desc.BindFlags=D3D11_BIND_SHADER_RESOURCE;D3D11_SUBRESOURCE_DATA data{&rgba,4,0};ComPtr<ID3D11Texture2D> texture;device_->CreateTexture2D(&desc,&data,&texture);device_->CreateShaderResourceView(texture.Get(),nullptr,&output);}
    ID3D11ShaderResourceView* material_texture(
        const World& world,
        const std::string& id,
        ID3D11ShaderResourceView* fallback,
        bool srgb) {
        if (id.empty()) return fallback;
        if (const auto cached = texture_cache_.find(id); cached != texture_cache_.end()) return cached->second.Get();
        const auto asset = world.assets.find(id);
        if (asset == world.assets.end() || !wic_) return fallback;

        ComPtr<IWICBitmapDecoder> decoder;
        if (FAILED(wic_->CreateDecoderFromFilename(
                asset->second.source.c_str(), nullptr, GENERIC_READ, WICDecodeMetadataCacheOnDemand, &decoder))) {
            return fallback;
        }
        ComPtr<IWICBitmapFrameDecode> frame;
        ComPtr<IWICFormatConverter> converter;
        if (FAILED(decoder->GetFrame(0, &frame)) || FAILED(wic_->CreateFormatConverter(&converter)) ||
            FAILED(converter->Initialize(
                frame.Get(), GUID_WICPixelFormat32bppRGBA, WICBitmapDitherTypeNone, nullptr, 0,
                WICBitmapPaletteTypeCustom))) {
            return fallback;
        }

        UINT width = 0;
        UINT height = 0;
        converter->GetSize(&width, &height);
        if (width == 0 || height == 0 || width > 16384 || height > 16384) return fallback;
        std::vector<std::uint8_t> pixels(static_cast<std::size_t>(width) * height * 4);
        if (FAILED(converter->CopyPixels(nullptr, width * 4, static_cast<UINT>(pixels.size()), pixels.data()))) {
            return fallback;
        }

        D3D11_TEXTURE2D_DESC desc{};
        desc.Width = width;
        desc.Height = height;
        desc.MipLevels = 0;
        desc.ArraySize = 1;
        desc.Format = srgb ? DXGI_FORMAT_R8G8B8A8_UNORM_SRGB : DXGI_FORMAT_R8G8B8A8_UNORM;
        desc.SampleDesc.Count = 1;
        desc.Usage = D3D11_USAGE_DEFAULT;
        desc.BindFlags = D3D11_BIND_SHADER_RESOURCE | D3D11_BIND_RENDER_TARGET;
        desc.MiscFlags = D3D11_RESOURCE_MISC_GENERATE_MIPS;
        ComPtr<ID3D11Texture2D> texture;
        if (FAILED(device_->CreateTexture2D(&desc, nullptr, &texture))) return fallback;
        context_->UpdateSubresource(texture.Get(), 0, nullptr, pixels.data(), width * 4, 0);

        D3D11_SHADER_RESOURCE_VIEW_DESC view_desc{};
        view_desc.Format = desc.Format;
        view_desc.ViewDimension = D3D11_SRV_DIMENSION_TEXTURE2D;
        view_desc.Texture2D.MostDetailedMip = 0;
        view_desc.Texture2D.MipLevels = UINT(-1);
        ComPtr<ID3D11ShaderResourceView> view;
        if (FAILED(device_->CreateShaderResourceView(texture.Get(), &view_desc, &view))) return fallback;
        context_->GenerateMips(view.Get());
        texture_cache_[id] = view;
        return view.Get();
    }
    bool create_render_texture(
        UINT width,UINT height,DXGI_FORMAT format,ComPtr<ID3D11Texture2D>& texture,
        ComPtr<ID3D11RenderTargetView>& target,ComPtr<ID3D11ShaderResourceView>& resource){
        D3D11_TEXTURE2D_DESC desc{};desc.Width=width;desc.Height=height;desc.MipLevels=desc.ArraySize=1;
        desc.Format=format;desc.SampleDesc.Count=1;desc.BindFlags=D3D11_BIND_RENDER_TARGET|D3D11_BIND_SHADER_RESOURCE;
        return SUCCEEDED(device_->CreateTexture2D(&desc,nullptr,&texture))&&
               SUCCEEDED(device_->CreateRenderTargetView(texture.Get(),nullptr,&target))&&
               SUCCEEDED(device_->CreateShaderResourceView(texture.Get(),nullptr,&resource));
    }
    bool create_gpu_timers(std::string& error){
        for(auto& frame:gpu_timing_){
            D3D11_QUERY_DESC desc{D3D11_QUERY_TIMESTAMP_DISJOINT,0};
            if(FAILED(device_->CreateQuery(&desc,&frame.disjoint))){error="GPU timing query allocation failed.";return false;}
            desc.Query=D3D11_QUERY_TIMESTAMP;
            if(FAILED(device_->CreateQuery(&desc,&frame.start))||FAILED(device_->CreateQuery(&desc,&frame.end))){error="GPU timestamp allocation failed.";return false;}
        }
        return true;
    }
    void begin_gpu_timing(){
        timing_started_=false;auto& frame=gpu_timing_[timing_cursor_];if(frame.pending)return;
        context_->Begin(frame.disjoint.Get());context_->End(frame.start.Get());timing_started_=true;
    }
    void end_gpu_timing(){
        if(!timing_started_)return;auto& frame=gpu_timing_[timing_cursor_];
        context_->End(frame.end.Get());context_->End(frame.disjoint.Get());frame.pending=true;
        timing_present_cursor_=timing_cursor_;
        timing_cursor_=(timing_cursor_+1)%gpu_timing_.size();timing_started_=false;
    }
    void resolve_gpu_timing(const RenderSettings& settings){
        resolved_gpu_sample_count_=0;
        for(auto& frame:gpu_timing_){
            if(!frame.pending)continue;D3D11_QUERY_DATA_TIMESTAMP_DISJOINT disjoint{};
            if(context_->GetData(frame.disjoint.Get(),&disjoint,sizeof(disjoint),D3D11_ASYNC_GETDATA_DONOTFLUSH)!=S_OK)continue;
            UINT64 start=0,end=0;const bool valid=!disjoint.Disjoint&&
                context_->GetData(frame.start.Get(),&start,sizeof(start),D3D11_ASYNC_GETDATA_DONOTFLUSH)==S_OK&&
                context_->GetData(frame.end.Get(),&end,sizeof(end),D3D11_ASYNC_GETDATA_DONOTFLUSH)==S_OK;
            frame.pending=false;if(!valid||end<=start)continue;
            const float milliseconds=static_cast<float>((end-start)*1000.0/static_cast<double>(disjoint.Frequency));
            if(resolved_gpu_sample_count_<resolved_gpu_samples_ms_.size())
                resolved_gpu_samples_ms_[resolved_gpu_sample_count_++]=milliseconds;
            average_gpu_ms_=gpu_timing_samples_==0?milliseconds:average_gpu_ms_*0.9F+milliseconds*0.1F;++gpu_timing_samples_;
            // A vsynced timestamp span can include display pacing between queued draws.
            // Do not reduce image quality based on time spent waiting in Present.
            const float work_estimate=detail::pacing_adjusted_gpu_ms(milliseconds,frame.present_wall_ms,frame.vsync);
            average_gpu_work_ms_=gpu_work_estimate_initialized_?
                average_gpu_work_ms_*0.9F+work_estimate*0.1F:work_estimate;
            gpu_work_estimate_initialized_=true;
        }
        if(!settings.dynamic_resolution||gpu_timing_samples_<15)return;
        const float minimum=std::clamp(std::min(settings.minimum_render_scale,settings.maximum_render_scale),0.25F,1.0F);
        const float maximum=std::clamp(std::max(settings.minimum_render_scale,settings.maximum_render_scale),minimum,1.0F);
        const float target=std::max(1.0F,settings.target_frame_ms);
        if(average_gpu_work_ms_>target*1.05F)adaptive_render_scale_=std::max(minimum,adaptive_render_scale_-0.05F);
        else if(average_gpu_work_ms_<target*0.82F)adaptive_render_scale_=std::min(maximum,adaptive_render_scale_+0.025F);
        gpu_timing_samples_=0;
    }
    bool create_frame_resources(float scale,std::string& error){
        if(width_<1||height_<1)return false;
        context_->OMSetRenderTargets(0,nullptr,nullptr);
        scene_texture_.Reset();scene_target_.Reset();scene_resource_.Reset();
        motion_texture_.Reset();motion_target_.Reset();motion_resource_.Reset();
        depth_texture_.Reset();depth_view_.Reset();
        D3D11_TEXTURE2D_DESC history_desc{};
        if(history_texture_[0])history_texture_[0]->GetDesc(&history_desc);
        const bool reuse_history=history_texture_[0]&&history_texture_[1]&&
            history_target_[0]&&history_target_[1]&&history_resource_[0]&&history_resource_[1]&&
            history_desc.Width==static_cast<UINT>(width_)&&history_desc.Height==static_cast<UINT>(height_);
        if(!reuse_history){
            for(int index=0;index<2;++index){history_texture_[index].Reset();history_target_[index].Reset();history_resource_[index].Reset();}
            history_valid_=false;history_index_=0;
        }
        current_render_scale_=std::clamp(scale,0.25F,1.0F);
        render_width_=std::max(1,static_cast<int>(std::lround(width_*current_render_scale_)));
        render_height_=std::max(1,static_cast<int>(std::lround(height_*current_render_scale_)));
        if(!create_render_texture(render_width_,render_height_,DXGI_FORMAT_R16G16B16A16_FLOAT,scene_texture_,scene_target_,scene_resource_)||
           !create_render_texture(render_width_,render_height_,DXGI_FORMAT_R16G16_FLOAT,motion_texture_,motion_target_,motion_resource_)||
           (!reuse_history&&(!create_render_texture(width_,height_,DXGI_FORMAT_R16G16B16A16_FLOAT,history_texture_[0],history_target_[0],history_resource_[0])||
                             !create_render_texture(width_,height_,DXGI_FORMAT_R16G16B16A16_FLOAT,history_texture_[1],history_target_[1],history_resource_[1])))){
            error="Temporal render-target allocation failed.";return false;
        }
        if(!reuse_history)++history_allocations_;
        D3D11_TEXTURE2D_DESC depth{};depth.Width=render_width_;depth.Height=render_height_;depth.MipLevels=depth.ArraySize=1;
        depth.Format=DXGI_FORMAT_D24_UNORM_S8_UINT;depth.SampleDesc.Count=1;depth.BindFlags=D3D11_BIND_DEPTH_STENCIL;
        if(FAILED(device_->CreateTexture2D(&depth,nullptr,&depth_texture_))||FAILED(device_->CreateDepthStencilView(depth_texture_.Get(),nullptr,&depth_view_))){
            error="Internal depth-target allocation failed.";return false;
        }
        error.clear();return true;
    }
    bool create_shadow(std::string& error){D3D11_TEXTURE2D_DESC desc{};desc.Width=2048;desc.Height=2048;desc.MipLevels=1;desc.ArraySize=1;desc.Format=DXGI_FORMAT_R32_TYPELESS;desc.SampleDesc.Count=1;desc.BindFlags=D3D11_BIND_DEPTH_STENCIL|D3D11_BIND_SHADER_RESOURCE;if(FAILED(device_->CreateTexture2D(&desc,nullptr,&shadow_texture_))){error="Shadow-map allocation failed.";return false;}D3D11_DEPTH_STENCIL_VIEW_DESC dsv{};dsv.Format=DXGI_FORMAT_D32_FLOAT;dsv.ViewDimension=D3D11_DSV_DIMENSION_TEXTURE2D;device_->CreateDepthStencilView(shadow_texture_.Get(),&dsv,&shadow_view_);D3D11_SHADER_RESOURCE_VIEW_DESC srv{};srv.Format=DXGI_FORMAT_R32_FLOAT;srv.ViewDimension=D3D11_SRV_DIMENSION_TEXTURE2D;srv.Texture2D.MipLevels=1;device_->CreateShaderResourceView(shadow_texture_.Get(),&srv,&shadow_srv_);return true;}
    UINT bind_geometry(GpuMesh* mesh=nullptr){UINT stride=sizeof(Vertex),offset=0;context_->IASetInputLayout(layout_.Get());ID3D11Buffer* vertices_buffer=mesh?mesh->vertices.Get():vertex_buffer_.Get();if(mesh&&mesh->cpu_skin_active){const auto cached=mesh->cpu_skin_frames.find(mesh->skin_binding_id);if(cached!=mesh->cpu_skin_frames.end()&&cached->second.gpu_vertices&&cached->second.gpu_frame==frame_index_)vertices_buffer=cached->second.gpu_vertices.Get();}context_->IASetVertexBuffers(0,1,&vertices_buffer,&stride,&offset);context_->IASetIndexBuffer(mesh?mesh->indices.Get():index_buffer_.Get(),mesh?DXGI_FORMAT_R32_UINT:DXGI_FORMAT_R16_UINT,0);context_->IASetPrimitiveTopology(D3D11_PRIMITIVE_TOPOLOGY_TRIANGLELIST);context_->VSSetConstantBuffers(0,1,constants_.GetAddressOf());context_->PSSetConstantBuffers(0,1,constants_.GetAddressOf());return mesh?mesh->index_count:static_cast<UINT>(std::size(indices));}
    XMMATRIX transform_matrix(const Transform& transform,const WorldVector3& origin)const{
        return XMMatrixScaling(transform.scale.x,transform.scale.y,transform.scale.z)*
               XMMatrixRotationRollPitchYaw(XMConvertToRadians(transform.rotation.x),XMConvertToRadians(transform.rotation.y),XMConvertToRadians(transform.rotation.z))*
               XMMatrixTranslation(static_cast<float>(transform.position.x-origin.x),static_cast<float>(transform.position.y-origin.y),static_cast<float>(transform.position.z-origin.z));
    }
    static std::string normalized_name(std::string value){
        std::transform(value.begin(),value.end(),value.begin(),[](unsigned char character){return static_cast<char>(std::tolower(character));});
        return value;
    }
    static float lighting_model_code(const std::string& value){
        const auto mode=normalized_name(value);
        if(mode=="stylized"||mode=="stylized_pbr")return 1.0F;
        if(mode=="toon"||mode=="toony"||mode=="cel")return 2.0F;
        if(mode=="unlit"||mode=="flat")return 3.0F;
        return 0.0F;
    }
    static float gi_mode_code(const std::string& value){
        const auto mode=normalized_name(value);
        if(mode=="off"||mode=="none")return 0.0F;
        if(mode=="hemisphere"||mode=="sky")return 1.0F;
        return 2.0F;
    }
    void update_constants(const Transform& transform,const Transform& previous_transform,const Renderable& material,
                          XMMATRIX vp,XMMATRIX previous_vp,XMMATRIX lvp,XMVECTOR eye){
        const XMMATRIX world=transform_matrix(transform,current_render_origin_);
        const XMMATRIX previous_world=transform_matrix(previous_transform,previous_render_origin_);
        D3D11_MAPPED_SUBRESOURCE mapped{};context_->Map(constants_.Get(),0,D3D11_MAP_WRITE_DISCARD,0,&mapped);
        auto* c=static_cast<Constants*>(mapped.pData);
        XMStoreFloat4x4(&c->world,XMMatrixTranspose(world));XMStoreFloat4x4(&c->view_projection,XMMatrixTranspose(vp));
        XMStoreFloat4x4(&c->light_view_projection,XMMatrixTranspose(lvp));XMStoreFloat4x4(&c->previous_world,XMMatrixTranspose(previous_world));
        XMStoreFloat4x4(&c->previous_view_projection,XMMatrixTranspose(previous_vp));
        c->base_metallic={material.base_color.x,material.base_color.y,material.base_color.z,material.metallic};
        c->light_roughness={current_sun_.direction.x,current_sun_.direction.y,current_sun_.direction.z,material.roughness};
        c->sun_color_intensity={current_sun_.color.x,current_sun_.color.y,current_sun_.color.z,current_sun_.intensity};
        XMStoreFloat4(&c->camera,eye);
        c->environment={current_environment_intensity_,lighting_model_code(current_render_settings_.lighting_model),
                        gi_mode_code(current_render_settings_.global_illumination),current_render_settings_.indirect_intensity};
        c->sky={current_render_settings_.sky_color.x,current_render_settings_.sky_color.y,current_render_settings_.sky_color.z,0};
        c->ground={current_render_settings_.ground_color.x,current_render_settings_.ground_color.y,current_render_settings_.ground_color.z,0};
        c->style={std::max(2.0F,current_render_settings_.toon_bands),std::max(0.0F,current_render_settings_.rim_intensity),
                  current_sun_.casts_shadow?1.0F:0.0F,std::max(1.0F,current_sun_.angular_radius_degrees/0.266F)};
        c->bounce_position_radius=current_bounce_positions_;c->bounce_color_intensity=current_bounce_colors_;
        const XMFLOAT3 local_center{static_cast<float>(transform.position.x-current_render_origin_.x),
                                    static_cast<float>(transform.position.y-current_render_origin_.y),
                                    static_cast<float>(transform.position.z-current_render_origin_.z)};
        for(std::size_t index=0;index<current_bounce_count_;++index){const auto& source=current_bounce_positions_[index];
            const float dx=source.x-local_center.x,dy=source.y-local_center.y,dz=source.z-local_center.z;
            if(dx*dx+dy*dy+dz*dz<1.0e-6F)c->bounce_color_intensity[index].w=0.0F;
        }
        c->bounce_settings={static_cast<float>(current_bounce_count_),0,0,0};
        context_->Unmap(constants_.Get(),0);
    }
    void update_post_constants(float sharpness){
        D3D11_MAPPED_SUBRESOURCE mapped{};context_->Map(post_constants_.Get(),0,D3D11_MAP_WRITE_DISCARD,0,&mapped);
        auto* constants=static_cast<PostConstants*>(mapped.pData);
        constants->temporal={1.0F/render_width_,1.0F/render_height_,history_valid_&&temporal_enabled_?1.0F:0.0F,0.9F};
        constants->display={1.0F/width_,1.0F/height_,std::clamp(sharpness,0.0F,1.0F),0};
        context_->Unmap(post_constants_.Get(),0);context_->PSSetConstantBuffers(1,1,post_constants_.GetAddressOf());
    }
    void update_sky_constants(XMMATRIX inverse_view_projection,XMVECTOR eye){
        D3D11_MAPPED_SUBRESOURCE mapped{};context_->Map(sky_constants_.Get(),0,D3D11_MAP_WRITE_DISCARD,0,&mapped);auto* constants=static_cast<SkyConstants*>(mapped.pData);
        XMStoreFloat4x4(&constants->inverse_view_projection,XMMatrixTranspose(inverse_view_projection));XMStoreFloat4(&constants->camera,eye);
        constants->sun_direction_radius={current_sun_.direction.x,current_sun_.direction.y,current_sun_.direction.z,current_sun_.angular_radius_degrees};
        constants->sun_color_intensity={current_sun_.color.x,current_sun_.color.y,current_sun_.color.z,current_sun_.intensity};
        constants->sky={current_render_settings_.sky_color.x,current_render_settings_.sky_color.y,current_render_settings_.sky_color.z,0};
        constants->ground={current_render_settings_.ground_color.x,current_render_settings_.ground_color.y,current_render_settings_.ground_color.z,0};
        constants->atmosphere={current_render_settings_.atmosphere_density,current_render_settings_.atmospheric_haze,current_render_settings_.horizon_falloff,0};
        context_->Unmap(sky_constants_.Get(),0);context_->PSSetConstantBuffers(2,1,sky_constants_.GetAddressOf());
    }
    bool is_builtin_cube(const World& world,const Renderable& material)const{
        if(material.mesh_asset.empty()||material.mesh_asset=="builtin:cube")return true;
        const auto asset=world.assets.find(material.mesh_asset);
        return asset!=world.assets.end()&&
               asset->second.source.filename()==std::filesystem::path(L"builtin:cube");
    }
    static float cube_radius(const Transform& transform){
        return 0.8660255F*std::max({std::abs(transform.scale.x),std::abs(transform.scale.y),std::abs(transform.scale.z)});
    }
    bool render_sphere(const Transform& transform,const GpuMesh* mesh,XMVECTOR& center,float& radius)const{
        if(!mesh||!mesh->bounds_valid)return false;
        const XMFLOAT3 local=mesh->bounds_center;
        center=XMVector3TransformCoord(XMVectorSet(local.x,local.y,local.z,1),
                                       transform_matrix(transform,current_render_origin_));
        const float largest_scale=std::max({std::abs(transform.scale.x),std::abs(transform.scale.y),std::abs(transform.scale.z)});
        radius=mesh->bounds_radius*largest_scale+0.01F;
        return std::isfinite(radius)&&std::isfinite(XMVectorGetX(center))&&
               std::isfinite(XMVectorGetY(center))&&std::isfinite(XMVectorGetZ(center));
    }
    bool sphere_intersects_camera_frustum(XMVECTOR bounds_center,float radius,XMMATRIX view,float fov_degrees,float aspect)const{
        const XMVECTOR center=XMVector3TransformCoord(bounds_center,view);
        const float x=XMVectorGetX(center),y=XMVectorGetY(center),z=XMVectorGetZ(center);
        if(!std::isfinite(radius)||!std::isfinite(x)||!std::isfinite(y)||!std::isfinite(z)||
           !std::isfinite(fov_degrees)||!std::isfinite(aspect)||aspect<=0)return true;
        if(z+radius<0.05F||z-radius>5000.0F)return false;
        const float tan_y=std::tan(XMConvertToRadians(fov_degrees)*0.5F),tan_x=tan_y*aspect;
        if(!std::isfinite(tan_x)||tan_x<=0)return true;
        // The margin covers a sphere against each side plane plus temporal
        // projection jitter and float rounding at the boundary.
        const float margin=radius+0.1F;
        const float jitter_distance=std::max(0.0F,z)*2.0F;
        return std::abs(x)<=z*tan_x+margin*std::sqrt(1.0F+tan_x*tan_x)+
                            jitter_distance*tan_x/float(std::max(1,render_width_))&&
               std::abs(y)<=z*tan_y+margin*std::sqrt(1.0F+tan_y*tan_y)+
                            jitter_distance*tan_y/float(std::max(1,render_height_));
    }
    bool cube_intersects_camera_frustum(const Transform& transform,XMMATRIX view,float fov_degrees,float aspect)const{
        const float radius=cube_radius(transform);
        const XMVECTOR center=XMVector3TransformCoord(
            XMVectorSet(static_cast<float>(transform.position.x-current_render_origin_.x),
                        static_cast<float>(transform.position.y-current_render_origin_.y),
                        static_cast<float>(transform.position.z-current_render_origin_.z),1),view);
        const float x=XMVectorGetX(center),y=XMVectorGetY(center),z=XMVectorGetZ(center);
        if(!std::isfinite(radius)||!std::isfinite(x)||!std::isfinite(y)||!std::isfinite(z)||
           !std::isfinite(fov_degrees)||!std::isfinite(aspect)||aspect<=0)return true;
        if(z+radius<0.05F||z-radius>5000.0F)return false;
        const float tan_y=std::tan(XMConvertToRadians(fov_degrees)*0.5F),tan_x=tan_y*aspect;
        if(!std::isfinite(tan_x)||tan_x<=0)return true;
        const float margin=radius+0.1F;
        const float jitter_distance=std::max(0.0F,z)*2.0F;
        return std::abs(x)<=z*tan_x+margin*std::sqrt(1.0F+tan_x*tan_x)+
                            jitter_distance*tan_x/float(std::max(1,render_width_))&&
               std::abs(y)<=z*tan_y+margin*std::sqrt(1.0F+tan_y*tan_y)+
                            jitter_distance*tan_y/float(std::max(1,render_height_));
    }
    bool sphere_intersects_shadow_volume(XMVECTOR bounds_center,float radius,XMMATRIX light_view)const{
        const XMVECTOR center=XMVector3TransformCoord(bounds_center,light_view);
        const float x=XMVectorGetX(center),y=XMVectorGetY(center),z=XMVectorGetZ(center);
        if(!std::isfinite(radius)||!std::isfinite(x)||!std::isfinite(y)||!std::isfinite(z))return true;
        return x+radius>=-30.0F&&x-radius<=30.0F&&
               y+radius>=-30.0F&&y-radius<=30.0F&&
               z+radius>=0.1F&&z-radius<=100.0F;
    }
    bool cube_intersects_shadow_volume(const Transform& transform,XMMATRIX light_view)const{
        const float radius=cube_radius(transform);
        const XMVECTOR center=XMVector3TransformCoord(
            XMVectorSet(static_cast<float>(transform.position.x-current_render_origin_.x),
                        static_cast<float>(transform.position.y-current_render_origin_.y),
                        static_cast<float>(transform.position.z-current_render_origin_.z),1),light_view);
        const float x=XMVectorGetX(center),y=XMVectorGetY(center),z=XMVectorGetZ(center);
        if(!std::isfinite(radius)||!std::isfinite(x)||!std::isfinite(y)||!std::isfinite(z))return true;
        return x+radius>=-30.0F&&x-radius<=30.0F&&
               y+radius>=-30.0F&&y-radius<=30.0F&&
               z+radius>=0.1F&&z-radius<=100.0F;
    }
    void draw_shadow(const World& world,XMMATRIX light_view,XMMATRIX lvp){
        context_->ClearDepthStencilView(shadow_view_.Get(),D3D11_CLEAR_DEPTH,1,0);
        if(!current_sun_.casts_shadow)return;
        context_->OMSetRenderTargets(0,nullptr,shadow_view_.Get());context_->RSSetState(shadow_rasterizer_.Get());
        D3D11_VIEWPORT viewport{0,0,2048,2048,0,1};context_->RSSetViewports(1,&viewport);
        context_->VSSetShader(shadow_shader_.Get(),nullptr,0);context_->PSSetShader(nullptr,nullptr,0);
        for(const auto& [entity,material]:world.renderables){
            const auto transform=world.transforms.find(entity);
            if(!material.casts_shadow||transform==world.transforms.end())continue;
            GpuMesh* mesh=is_builtin_cube(world,material)?nullptr:imported_mesh(world,material.mesh_asset);
            XMVECTOR bounds_center{};float bounds_radius{};
            bool in_shadow=true;
            if(material.skin_binding.empty())in_shadow=mesh?
                (!render_sphere(transform->second,mesh,bounds_center,bounds_radius)||
                 sphere_intersects_shadow_volume(bounds_center,bounds_radius,light_view)):
                cube_intersects_shadow_volume(transform->second,light_view);
            if(!in_shadow)continue;
            bind_skinning(world,material.skin_binding,mesh);
            if(!skinning_error_.empty())return;
            const UINT count=bind_geometry(mesh);
            update_constants(transform->second,transform->second,material,XMMatrixIdentity(),XMMatrixIdentity(),lvp,XMVectorZero());
            context_->DrawIndexed(count,0,0);++submitted_shadow_draws_;unbind_skinning();
        }
        context_->RSSetState(default_rasterizer_.Get());
    }
    std::pair<std::string,float> reflection_environment(const World& world,const WorldVector3& position)const{
        const ReflectionProbe* selected=nullptr;
        double selected_distance=std::numeric_limits<double>::max();
        for(const auto& [entity,probe]:world.reflection_probes){
            const auto transform=world.transforms.find(entity);if(transform==world.transforms.end())continue;
            const double x=std::abs(position.x-transform->second.position.x)/std::max(0.001,static_cast<double>(probe.half_extents.x));
            const double y=std::abs(position.y-transform->second.position.y)/std::max(0.001,static_cast<double>(probe.half_extents.y));
            const double z=std::abs(position.z-transform->second.position.z)/std::max(0.001,static_cast<double>(probe.half_extents.z));
            if(x>1||y>1||z>1)continue;
            const double distance=x*x+y*y+z*z;
            if(!selected||probe.priority>selected->priority||(probe.priority==selected->priority&&distance<selected_distance)){
                selected=&probe;selected_distance=distance;
            }
        }
        if(selected&&!selected->environment_texture.empty())return {selected->environment_texture,selected->intensity};
        return {world.render_settings.environment_texture,world.render_settings.environment_intensity};
    }
    DirectionalLight active_sun(const World& world)const{
        DirectionalLight result{};float best=-1.0F;
        for(const auto& [unused,light]:world.lights){static_cast<void>(unused);if(light.intensity>best){result=light;best=light.intensity;}}
        return result;
    }
    void build_dynamic_gi_sources(const World& world){
        current_bounce_count_=0;current_bounce_positions_.fill({0,0,0,0});current_bounce_colors_.fill({0,0,0,0});
        if(!current_render_settings_.dynamic_diffuse_gi)return;
        struct Candidate{XMFLOAT4 position;XMFLOAT4 color;float score;};std::vector<Candidate> candidates;
        for(const auto& [entity,material]:world.renderables){
            const auto transform=world.transforms.find(entity);if(transform==world.transforms.end())continue;
            const float scale=std::max({std::abs(transform->second.scale.x),std::abs(transform->second.scale.y),std::abs(transform->second.scale.z),0.1F});
            const float strength=std::max(0.0F,current_render_settings_.dynamic_gi_intensity)*0.15F;
            Candidate candidate{
                {static_cast<float>(transform->second.position.x-current_render_origin_.x),static_cast<float>(transform->second.position.y-current_render_origin_.y),static_cast<float>(transform->second.position.z-current_render_origin_.z),std::max(scale*2.0F,current_render_settings_.dynamic_gi_distance)},
                {material.base_color.x*current_sun_.color.x,material.base_color.y*current_sun_.color.y,material.base_color.z*current_sun_.color.z,strength*current_sun_.intensity},
                scale*scale*(material.base_color.x+material.base_color.y+material.base_color.z),
            };candidates.push_back(candidate);
        }
        std::sort(candidates.begin(),candidates.end(),[](const Candidate& left,const Candidate& right){return left.score>right.score;});
        current_bounce_count_=std::min<std::size_t>({candidates.size(),current_bounce_positions_.size(),static_cast<std::size_t>(std::max(0,current_render_settings_.maximum_dynamic_gi_sources))});
        for(std::size_t index=0;index<current_bounce_count_;++index){current_bounce_positions_[index]=candidates[index].position;current_bounce_colors_[index]=candidates[index].color;}
    }
    static WorldVector3 render_origin_for(const WorldVector3& camera,const SimulationSettings& settings){
        const double threshold=std::max(1.0e-12,settings.render_origin_threshold_world_units);
        return {std::nearbyint(camera.x/threshold)*threshold,
                std::nearbyint(camera.y/threshold)*threshold,
                std::nearbyint(camera.z/threshold)*threshold};
    }
    WorldVector3 active_camera(const World& world){for(const auto& [entity,camera]:world.cameras)if(camera.active&&world.transforms.contains(entity))return world.transforms.at(entity).position;return {0,4,-14};}
    WorldVector3 active_camera_target(const World& world){for(const auto& [unused,camera]:world.cameras){static_cast<void>(unused);if(camera.active)return camera.look_at;}return {0,1,0};}
    float active_fov(const World& world){for(const auto& [unused,camera]:world.cameras){static_cast<void>(unused);if(camera.active)return camera.field_of_view_degrees;}return 55;}
    struct ComLifetime {
        bool initialized{false};
        ~ComLifetime(){if(initialized)CoUninitialize();}
    } com_lifetime_;
    int width_{},height_{},render_width_{},render_height_{};
    float current_environment_intensity_{1.0F},current_render_scale_{1.0F};
    DirectionalLight current_sun_{};RenderSettings current_render_settings_{};
    std::array<XMFLOAT4,8> current_bounce_positions_{},current_bounce_colors_{};std::size_t current_bounce_count_{0};
    WorldVector3 current_render_origin_{},previous_render_origin_{};bool previous_render_origin_valid_{false};
    bool history_valid_{false},previous_view_projection_valid_{false};int history_index_{0};XMMATRIX previous_view_projection_{};
    std::size_t history_allocations_{0};
    bool dynamic_resolution_active_{false},timing_started_{false},temporal_enabled_{false};float adaptive_render_scale_{1.0F},average_gpu_ms_{0.0F},average_gpu_work_ms_{0.0F};
    bool gpu_work_estimate_initialized_{false};
    bool vsync_{true};
    bool cpu_skinning_diagnostic_{false};
    float ui_scale_{1.0F};
    std::array<float,4> resolved_gpu_samples_ms_{};
    std::size_t resolved_gpu_sample_count_{0};
    std::size_t timing_cursor_{0},gpu_timing_samples_{0},timing_present_cursor_{std::numeric_limits<std::size_t>::max()};std::uint64_t frame_index_{0};std::array<GpuTimingFrame,4> gpu_timing_;
    std::size_t gpu_skinned_draws_{0},cpu_skinned_draws_{0};
    float present_wall_ms_{0.0F},cpu_skin_wall_ms_{0.0F};
    float shadow_wall_ms_{0.0F},geometry_wall_ms_{0.0F},post_wall_ms_{0.0F};
    std::size_t submitted_geometry_draws_{0},submitted_shadow_draws_{0};
    GpuAdapterInfo adapter_info_{};
    ComPtr<ID3D11Device> device_;ComPtr<ID3D11DeviceContext> context_;ComPtr<IDXGISwapChain> swap_chain_;
    ComPtr<ID2D1Factory1> d2d_factory_;ComPtr<ID2D1RenderTarget> ui_target_;
    ComPtr<IWICBitmap> ui_bitmap_;
    ComPtr<ID2D1SolidColorBrush> ui_brush_;
    struct UiImageCacheEntry{
        ComPtr<IWICBitmap> decoded;
        ComPtr<ID2D1Bitmap> bitmap;
        std::filesystem::file_time_type modified{};
        std::uintmax_t size{0};
    };
    std::unordered_map<std::wstring,UiImageCacheEntry> ui_image_cache_;
    ComPtr<ID3D11Texture2D> ui_texture_;ComPtr<ID3D11ShaderResourceView> ui_resource_;
    std::string ui_content_key_;
    std::size_t ui_compositions_{0},ui_texture_creations_{0},ui_image_decodes_{0};
    std::vector<std::uint8_t> ui_pixels_;
    float ui_bitmap_ms_{0.0F},ui_draw_ms_{0.0F},ui_copy_ms_{0.0F},ui_text_ms_{0.0F},ui_blend_ms_{0.0F},ui_upload_ms_{0.0F};
    ComPtr<ID3D11BlendState> ui_blend_state_;
    ComPtr<ID3D11RenderTargetView> render_target_,display_target_,scene_target_,motion_target_;
    std::array<ComPtr<ID3D11RenderTargetView>,2> history_target_;
    ComPtr<ID3D11Texture2D> back_buffer_,display_texture_,depth_texture_,shadow_texture_,scene_texture_,motion_texture_;
    std::array<ComPtr<ID3D11Texture2D>,2> history_texture_;
    ComPtr<ID3D11DepthStencilView> depth_view_,shadow_view_;
    ComPtr<ID3D11ShaderResourceView> shadow_srv_,white_texture_,normal_texture_,black_texture_,scene_resource_,motion_resource_;
    std::array<ComPtr<ID3D11ShaderResourceView>,2> history_resource_;
    ComPtr<ID3D11VertexShader> vertex_shader_,shadow_shader_,post_vertex_shader_;
    ComPtr<ID3D11PixelShader> pixel_shader_,temporal_shader_,display_shader_,atmosphere_shader_,ui_shader_;
    RenderBackend requested_backend_{RenderBackend::automatic};
    ComPtr<ID3D11InputLayout> layout_;ComPtr<ID3D11Buffer> vertex_buffer_,index_buffer_,constants_,post_constants_,sky_constants_,skin_constants_;
    ComPtr<ID3D11SamplerState> shadow_sampler_,material_sampler_;ComPtr<IWICImagingFactory> wic_;
    ComPtr<ID3D11RasterizerState> default_rasterizer_,shadow_rasterizer_;
    std::unordered_map<std::string,ComPtr<ID3D11ShaderResourceView>> texture_cache_;std::unordered_map<std::string,GpuMesh> mesh_cache_;
    std::unordered_map<std::string,CpuSkinData> cpu_skin_cache_;
    std::unordered_map<std::string,std::vector<float>> inverse_bind_frame_cache_;
    std::size_t inverse_bind_reads_{0},inverse_bind_cache_hits_{0};
    std::string skinning_error_;
    std::unordered_map<std::string,GpuSkinStreams> gpu_skin_stream_cache_;
    std::unordered_map<std::string,GpuSkinData> gpu_skin_cache_;
    std::unordered_map<EntityId,Transform> previous_transforms_;
};

#else
class GpuRenderer::Implementation { public: explicit Implementation(RenderBackend requested):requested_(requested){}void set_vsync(bool enabled)noexcept{vsync_=enabled;}void set_cpu_skinning_diagnostic(bool)noexcept{}void set_ui_scale(float)noexcept{}bool initialize(void*,int,int,std::string& e){e="No native presentation backend is available on this platform build.";return false;}bool resize(int,int,std::string& e){return initialize(nullptr,0,0,e);}bool render(const World&,std::string& e,const std::filesystem::path*){return initialize(nullptr,0,0,e);}bool capture(const std::filesystem::path&,std::string& e){return initialize(nullptr,0,0,e);}bool ready()const noexcept{return false;}GpuRenderProfile profile()const noexcept{GpuRenderProfile result;result.vsync=vsync_;return result;}GpuAdapterInfo adapter_info()const{return {};}RenderBackend backend()const noexcept{return requested_==RenderBackend::automatic?RenderBackend::null_backend:requested_;}RenderBackendCapabilities capabilities()const{return {backend(),backend()==RenderBackend::metal?"Metal":backend()==RenderBackend::vulkan?"Vulkan":backend()==RenderBackend::d3d12?"Direct3D 12":"Null",backend()==RenderBackend::null_backend,false,false,false,false};}RenderBackend requested_;bool vsync_{true}; };
#endif

GpuRenderer::GpuRenderer(RenderBackend requested):implementation_(std::make_unique<Implementation>(requested)){}
GpuRenderer::~GpuRenderer()=default;
bool GpuRenderer::initialize(void* w,int x,int y,std::string& e){return implementation_->initialize(w,x,y,e);}bool GpuRenderer::resize(int x,int y,std::string& e){return implementation_->resize(x,y,e);}bool GpuRenderer::render(const World& w,std::string& e,const std::filesystem::path* p){return implementation_->render(w,e,p);}bool GpuRenderer::capture_bmp(const std::filesystem::path& p,std::string& e){return implementation_->capture(p,e);}bool GpuRenderer::ready()const noexcept{return implementation_->ready();}
void GpuRenderer::set_vsync(bool enabled)noexcept{implementation_->set_vsync(enabled);}
void GpuRenderer::set_cpu_skinning_diagnostic(bool enabled)noexcept{implementation_->set_cpu_skinning_diagnostic(enabled);}
void GpuRenderer::set_ui_scale(float scale)noexcept{implementation_->set_ui_scale(scale);}
GpuRenderProfile GpuRenderer::profile()const noexcept{return implementation_->profile();}
GpuAdapterInfo GpuRenderer::adapter_info()const{return implementation_->adapter_info();}
RenderBackend GpuRenderer::backend()const noexcept{return implementation_->backend();}
RenderBackendCapabilities GpuRenderer::capabilities()const{return implementation_->capabilities();}

}  // namespace tc::runtime
