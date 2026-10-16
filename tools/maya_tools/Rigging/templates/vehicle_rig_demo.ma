//Maya ASCII 2023 scene
//Name: vehicle_rig_demo.ma
//Last modified: Wed, Oct 14, 2026 02:49:16 PM
//Codeset: 1252
requires maya "2023";
currentUnit -l centimeter -a degree -t film;
fileInfo "application" "maya";
fileInfo "product" "Maya 2023";
fileInfo "version" "2023";
fileInfo "cutIdentifier" "202405151550-05a853e76d";
fileInfo "osv" "Windows 10 Home v2009 (Build: 19045)";
fileInfo "UUID" "EAFCDE31-423D-C76B-2F45-8E98CF3D38F7";
createNode transform -s -n "persp";
	rename -uid "79351563-4312-EB39-D7F7-4CAED9B3DE6E";
	setAttr ".v" no;
	setAttr ".t" -type "double3" 28 21 28 ;
	setAttr ".r" -type "double3" -27.938352729602379 44.999999999999972 -5.172681101354183e-14 ;
createNode camera -s -n "perspShape" -p "persp";
	rename -uid "7EE3C9C2-43E2-E943-1C36-4EB1F180E056";
	setAttr -k off ".v" no;
	setAttr ".fl" 34.999999999999993;
	setAttr ".coi" 44.82186966202994;
	setAttr ".imn" -type "string" "persp";
	setAttr ".den" -type "string" "persp_depth";
	setAttr ".man" -type "string" "persp_mask";
	setAttr ".hc" -type "string" "viewSet -p %camera";
createNode transform -s -n "top";
	rename -uid "CA336EF2-4F6E-3A34-421B-9C927ABE22FE";
	setAttr ".v" no;
	setAttr ".t" -type "double3" 0 1000.1 0 ;
	setAttr ".r" -type "double3" -90 0 0 ;
createNode camera -s -n "topShape" -p "top";
	rename -uid "E6F49C31-4429-B15F-3DA3-1DB0EE876C28";
	setAttr -k off ".v" no;
	setAttr ".rnd" no;
	setAttr ".coi" 1000.1;
	setAttr ".ow" 30;
	setAttr ".imn" -type "string" "top";
	setAttr ".den" -type "string" "top_depth";
	setAttr ".man" -type "string" "top_mask";
	setAttr ".hc" -type "string" "viewSet -t %camera";
	setAttr ".o" yes;
createNode transform -s -n "front";
	rename -uid "9E6275BB-4CD7-E444-EA79-7D9EDA5AB41E";
	setAttr ".v" no;
	setAttr ".t" -type "double3" 0 0 1000.1 ;
createNode camera -s -n "frontShape" -p "front";
	rename -uid "3ABD350E-4EAC-9AB3-9DEB-1083C2D2A2C4";
	setAttr -k off ".v" no;
	setAttr ".rnd" no;
	setAttr ".coi" 1000.1;
	setAttr ".ow" 30;
	setAttr ".imn" -type "string" "front";
	setAttr ".den" -type "string" "front_depth";
	setAttr ".man" -type "string" "front_mask";
	setAttr ".hc" -type "string" "viewSet -f %camera";
	setAttr ".o" yes;
createNode transform -s -n "side";
	rename -uid "D20B9094-409F-D5E5-1E16-3AB953206D19";
	setAttr ".v" no;
	setAttr ".t" -type "double3" 1000.1 0 0 ;
	setAttr ".r" -type "double3" 0 90 0 ;
createNode camera -s -n "sideShape" -p "side";
	rename -uid "E5B113F7-4FBC-919D-046C-05AB0F5A5AA8";
	setAttr -k off ".v" no;
	setAttr ".rnd" no;
	setAttr ".coi" 1000.1;
	setAttr ".ow" 30;
	setAttr ".imn" -type "string" "side";
	setAttr ".den" -type "string" "side_depth";
	setAttr ".man" -type "string" "side_mask";
	setAttr ".hc" -type "string" "viewSet -s %camera";
	setAttr ".o" yes;
createNode joint -n "vehicle_root_JNT";
	rename -uid "5076DF3C-44A5-058B-ECAB-2AB74A80E129";
	addAttr -ci true -sn "tcVehicleRole" -ln "tcVehicleRole" -dt "string";
	addAttr -ci true -sn "tcVehicleSchema" -ln "tcVehicleSchema" -dt "string";
	addAttr -ci true -sn "tcTemplateVersion" -ln "tcTemplateVersion" -at "long";
	addAttr -ci true -sn "tcUpAxis" -ln "tcUpAxis" -dt "string";
	addAttr -ci true -sn "tcForwardAxis" -ln "tcForwardAxis" -dt "string";
	addAttr -ci true -sn "tcRightAxis" -ln "tcRightAxis" -dt "string";
	addAttr -ci true -sn "tcSceneLinearUnit" -ln "tcSceneLinearUnit" -dt "string";
	addAttr -ci true -sn "tcPortableLinearUnit" -ln "tcPortableLinearUnit" -dt "string";
	addAttr -ci true -sn "tcGroundQuery" -ln "tcGroundQuery" -dt "string";
	addAttr -ci true -sn "tcTransferPolicy" -ln "tcTransferPolicy" -dt "string";
	addAttr -ci true -sn "tcVehicleDefinition" -ln "tcVehicleDefinition" -dt "string";
	setAttr ".mnrl" -type "double3" -360 -360 -360 ;
	setAttr ".mxrl" -type "double3" 360 360 360 ;
	setAttr ".radi" 8;
	setAttr ".tcVehicleRole" -type "string" "root";
	setAttr ".tcVehicleSchema" -type "string" "tech_connector.vehicle_rig.v1";
	setAttr ".tcTemplateVersion" 1;
	setAttr ".tcUpAxis" -type "string" "Y";
	setAttr ".tcForwardAxis" -type "string" "Z";
	setAttr ".tcRightAxis" -type "string" "X";
	setAttr ".tcSceneLinearUnit" -type "string" "centimeter";
	setAttr ".tcPortableLinearUnit" -type "string" "meter";
	setAttr ".tcGroundQuery" -type "string" "raycast";
	setAttr ".tcTransferPolicy" -type "string" "reconstruct_live_solver_or_bake_animation";
	setAttr ".tcVehicleDefinition" -type "string" (
		"{\"chassis_joint\":\"vehicle_chassis_JNT\",\"coordinate_system\":{\"forward\":\"Z\",\"right\":\"X\",\"unit\":\"meter\",\"up\":\"Y\"},\"root_joint\":\"vehicle_root_JNT\",\"schema\":\"tech_connector.vehicle_rig.v1\",\"version\":1,\"wheels\":[{\"axle\":\"front\",\"braked\":true,\"contact_joint\":\"front_left_contact_JNT\",\"driven\":false,\"id\":\"front_left\",\"mount_joint\":\"front_left_mount_JNT\",\"mount_m\":[-0.8,0.05,1.2],\"radius_m\":0.34,\"steerable\":true,\"suspension_rest_length_m\":0.36,\"suspension_travel_m\":0.18,\"wheel_joint\":\"front_left_wheel_JNT\"},{\"axle\":\"front\",\"braked\":true,\"contact_joint\":\"front_right_contact_JNT\",\"driven\":false,\"id\":\"front_right\",\"mount_joint\":\"front_right_mount_JNT\",\"mount_m\":[0.8,0.05,1.2],\"radius_m\":0.34,\"steerable\":true,\"suspension_rest_length_m\":0.36,\"suspension_travel_m\":0.18,\"wheel_joint\":\"front_right_wheel_JNT\"},{\"axle\":\"rear\",\"braked\":true,\"contact_joint\":\"rear_left_contact_JNT\",\"driven\":true,\"id\":\"rear_left\",\"mount_joint\":\"rear_left_mount_JNT\",\"mount_m\":[-0.8,0.05,-1.2],\"radius_m\":0.34,\"steerable\":false,\"suspension_rest_length_m\":0.36,\"suspension_travel_m\":0.18,\"wheel_joint\":\"rear_left_wheel_JNT\"},{\"axle\":\"rear\",\"braked\":true,\"contact_joint\":\"rear_right_contact_JNT\",\"driven\":true,\"id\":\"rear_right\",\"mount_joint\":\"rear_right_mount_JNT\",\"mount_m\":[0.8,0.05,-1.2],\"radius_m\":0.34,\"steerable\":false,\"suspension_rest_length_m\":0.36,\"suspension_travel_m\":0.18,\"wheel_joint\":\"rear_right_wheel_JNT\"}]}");
createNode joint -n "vehicle_chassis_JNT" -p "vehicle_root_JNT";
	rename -uid "7D88EA53-4C7B-3C0A-F4E2-6AAE0822D6DB";
	addAttr -ci true -sn "tcVehicleRole" -ln "tcVehicleRole" -dt "string";
	addAttr -ci true -k true -sn "tcMassKg" -ln "tcMassKg" -min 0 -at "double";
	addAttr -ci true -k true -sn "tcMaximumSteerAngleDeg" -ln "tcMaximumSteerAngleDeg" 
		-min 0 -at "double";
	addAttr -ci true -k true -sn "tcEngineForceN" -ln "tcEngineForceN" -min 0 -at "double";
	addAttr -ci true -k true -sn "tcAerodynamicDrag" -ln "tcAerodynamicDrag" -min 0 
		-at "double";
	addAttr -ci true -k true -sn "tcRollingResistance" -ln "tcRollingResistance" -min 
		0 -at "double";
	addAttr -ci true -k true -sn "tcAntiRollStiffness" -ln "tcAntiRollStiffness" -min 
		0 -at "double";
	addAttr -ci true -k true -sn "tcCenterOfMassOffsetXM" -ln "tcCenterOfMassOffsetXM" 
		-at "double";
	addAttr -ci true -k true -sn "tcCenterOfMassOffsetYM" -ln "tcCenterOfMassOffsetYM" 
		-at "double";
	addAttr -ci true -k true -sn "tcCenterOfMassOffsetZM" -ln "tcCenterOfMassOffsetZM" 
		-at "double";
	setAttr ".mnrl" -type "double3" -360 -360 -360 ;
	setAttr ".mxrl" -type "double3" 360 360 360 ;
	setAttr ".radi" 7;
	setAttr ".tcVehicleRole" -type "string" "chassis";
	setAttr -k on ".tcMassKg" 1350;
	setAttr -k on ".tcMaximumSteerAngleDeg" 32;
	setAttr -k on ".tcEngineForceN" 8500;
	setAttr -k on ".tcAerodynamicDrag" 0.34;
	setAttr -k on ".tcRollingResistance" 0.015;
	setAttr -k on ".tcAntiRollStiffness" 7500;
	setAttr -k on ".tcCenterOfMassOffsetYM" -0.35;
createNode joint -n "front_left_mount_JNT" -p "vehicle_chassis_JNT";
	rename -uid "3CF8F55A-48CA-A2B8-5AF2-85BDDB744DFB";
	addAttr -ci true -sn "tcVehicleRole" -ln "tcVehicleRole" -dt "string";
	addAttr -ci true -sn "tcWheelId" -ln "tcWheelId" -dt "string";
	addAttr -ci true -sn "tcAxle" -ln "tcAxle" -dt "string";
	addAttr -ci true -sn "tcCollisionMask" -ln "tcCollisionMask" -dt "string";
	addAttr -ci true -k true -sn "tcRadiusM" -ln "tcRadiusM" -min 0 -at "double";
	addAttr -ci true -k true -sn "tcSuspensionRestLengthM" -ln "tcSuspensionRestLengthM" 
		-min 0 -at "double";
	addAttr -ci true -k true -sn "tcSuspensionTravelM" -ln "tcSuspensionTravelM" -min 
		0 -at "double";
	addAttr -ci true -k true -sn "tcSpringStiffness" -ln "tcSpringStiffness" -min 0 
		-at "double";
	addAttr -ci true -k true -sn "tcSpringDamping" -ln "tcSpringDamping" -min 0 -at "double";
	addAttr -ci true -k true -sn "tcBrakeTorqueNm" -ln "tcBrakeTorqueNm" -min 0 -at "double";
	addAttr -ci true -k true -sn "tcSteerable" -ln "tcSteerable" -min 0 -max 1 -at "bool";
	addAttr -ci true -k true -sn "tcDriven" -ln "tcDriven" -min 0 -max 1 -at "bool";
	addAttr -ci true -k true -sn "tcBraked" -ln "tcBraked" -min 0 -max 1 -at "bool";
	setAttr ".t" -type "double3" -80 5 120 ;
	setAttr ".mnrl" -type "double3" -360 -360 -360 ;
	setAttr ".mxrl" -type "double3" 360 360 360 ;
	setAttr ".radi" 4;
	setAttr ".tcVehicleRole" -type "string" "wheel_mount";
	setAttr ".tcWheelId" -type "string" "front_left";
	setAttr ".tcAxle" -type "string" "front";
	setAttr ".tcCollisionMask" -type "string" "world_static";
	setAttr -k on ".tcRadiusM" 0.34;
	setAttr -k on ".tcSuspensionRestLengthM" 0.36;
	setAttr -k on ".tcSuspensionTravelM" 0.18;
	setAttr -k on ".tcSpringStiffness" 32000;
	setAttr -k on ".tcSpringDamping" 4200;
	setAttr -k on ".tcBrakeTorqueNm" 1800;
	setAttr -k on ".tcSteerable" yes;
	setAttr -k on ".tcBraked" yes;
createNode joint -n "front_left_wheel_JNT" -p "front_left_mount_JNT";
	rename -uid "90495DEC-4338-E85D-D89B-E4B2B261B2D6";
	addAttr -ci true -sn "tcVehicleRole" -ln "tcVehicleRole" -dt "string";
	addAttr -ci true -sn "tcWheelId" -ln "tcWheelId" -dt "string";
	setAttr ".mnrl" -type "double3" -360 -360 -360 ;
	setAttr ".mxrl" -type "double3" 360 360 360 ;
	setAttr ".radi" 5;
	setAttr ".tcVehicleRole" -type "string" "wheel";
	setAttr ".tcWheelId" -type "string" "front_left";
createNode joint -n "front_left_contact_JNT" -p "front_left_wheel_JNT";
	rename -uid "3154C83D-40DF-B5FE-C074-52B5071C2B45";
	addAttr -ci true -sn "tcVehicleRole" -ln "tcVehicleRole" -dt "string";
	addAttr -ci true -sn "tcWheelId" -ln "tcWheelId" -dt "string";
	setAttr ".t" -type "double3" 0 -34.000000000000014 0 ;
	setAttr ".mnrl" -type "double3" -360 -360 -360 ;
	setAttr ".mxrl" -type "double3" 360 360 360 ;
	setAttr ".radi" 2;
	setAttr ".tcVehicleRole" -type "string" "ground_contact";
	setAttr ".tcWheelId" -type "string" "front_left";
createNode parentConstraint -n "front_left_wheel_parentConstraint" -p "front_left_wheel_JNT";
	rename -uid "58EB02ED-42A7-9932-363A-F0B68B2C72E3";
	addAttr -dcb 0 -ci true -k true -sn "w0" -ln "front_left_wheel_CTRLW0" -dv 1 -min 
		0 -at "double";
	setAttr -k on ".nds";
	setAttr -k off ".v";
	setAttr -k off ".tx";
	setAttr -k off ".ty";
	setAttr -k off ".tz";
	setAttr -k off ".rx";
	setAttr -k off ".ry";
	setAttr -k off ".rz";
	setAttr -k off ".sx";
	setAttr -k off ".sy";
	setAttr -k off ".sz";
	setAttr ".erp" yes;
	setAttr ".rst" -type "double3" 0 -35.999999999999993 0 ;
	setAttr -k on ".w0";
createNode joint -n "front_right_mount_JNT" -p "vehicle_chassis_JNT";
	rename -uid "70AF4E47-42A7-3AD4-73EC-BF9E96026626";
	addAttr -ci true -sn "tcVehicleRole" -ln "tcVehicleRole" -dt "string";
	addAttr -ci true -sn "tcWheelId" -ln "tcWheelId" -dt "string";
	addAttr -ci true -sn "tcAxle" -ln "tcAxle" -dt "string";
	addAttr -ci true -sn "tcCollisionMask" -ln "tcCollisionMask" -dt "string";
	addAttr -ci true -k true -sn "tcRadiusM" -ln "tcRadiusM" -min 0 -at "double";
	addAttr -ci true -k true -sn "tcSuspensionRestLengthM" -ln "tcSuspensionRestLengthM" 
		-min 0 -at "double";
	addAttr -ci true -k true -sn "tcSuspensionTravelM" -ln "tcSuspensionTravelM" -min 
		0 -at "double";
	addAttr -ci true -k true -sn "tcSpringStiffness" -ln "tcSpringStiffness" -min 0 
		-at "double";
	addAttr -ci true -k true -sn "tcSpringDamping" -ln "tcSpringDamping" -min 0 -at "double";
	addAttr -ci true -k true -sn "tcBrakeTorqueNm" -ln "tcBrakeTorqueNm" -min 0 -at "double";
	addAttr -ci true -k true -sn "tcSteerable" -ln "tcSteerable" -min 0 -max 1 -at "bool";
	addAttr -ci true -k true -sn "tcDriven" -ln "tcDriven" -min 0 -max 1 -at "bool";
	addAttr -ci true -k true -sn "tcBraked" -ln "tcBraked" -min 0 -max 1 -at "bool";
	setAttr ".t" -type "double3" 80 5 120 ;
	setAttr ".mnrl" -type "double3" -360 -360 -360 ;
	setAttr ".mxrl" -type "double3" 360 360 360 ;
	setAttr ".radi" 4;
	setAttr ".tcVehicleRole" -type "string" "wheel_mount";
	setAttr ".tcWheelId" -type "string" "front_right";
	setAttr ".tcAxle" -type "string" "front";
	setAttr ".tcCollisionMask" -type "string" "world_static";
	setAttr -k on ".tcRadiusM" 0.34;
	setAttr -k on ".tcSuspensionRestLengthM" 0.36;
	setAttr -k on ".tcSuspensionTravelM" 0.18;
	setAttr -k on ".tcSpringStiffness" 32000;
	setAttr -k on ".tcSpringDamping" 4200;
	setAttr -k on ".tcBrakeTorqueNm" 1800;
	setAttr -k on ".tcSteerable" yes;
	setAttr -k on ".tcBraked" yes;
createNode joint -n "front_right_wheel_JNT" -p "front_right_mount_JNT";
	rename -uid "AED2B3E2-4B38-FB10-6FC6-12BB98496D91";
	addAttr -ci true -sn "tcVehicleRole" -ln "tcVehicleRole" -dt "string";
	addAttr -ci true -sn "tcWheelId" -ln "tcWheelId" -dt "string";
	setAttr ".mnrl" -type "double3" -360 -360 -360 ;
	setAttr ".mxrl" -type "double3" 360 360 360 ;
	setAttr ".radi" 5;
	setAttr ".tcVehicleRole" -type "string" "wheel";
	setAttr ".tcWheelId" -type "string" "front_right";
createNode joint -n "front_right_contact_JNT" -p "front_right_wheel_JNT";
	rename -uid "8C858FA5-4FB1-F415-D2EA-FA92DB1C48EE";
	addAttr -ci true -sn "tcVehicleRole" -ln "tcVehicleRole" -dt "string";
	addAttr -ci true -sn "tcWheelId" -ln "tcWheelId" -dt "string";
	setAttr ".t" -type "double3" 0 -34.000000000000014 0 ;
	setAttr ".mnrl" -type "double3" -360 -360 -360 ;
	setAttr ".mxrl" -type "double3" 360 360 360 ;
	setAttr ".radi" 2;
	setAttr ".tcVehicleRole" -type "string" "ground_contact";
	setAttr ".tcWheelId" -type "string" "front_right";
createNode parentConstraint -n "front_right_wheel_parentConstraint" -p "front_right_wheel_JNT";
	rename -uid "99B4A18A-47D1-95B7-2563-159F1B4E26AF";
	addAttr -dcb 0 -ci true -k true -sn "w0" -ln "front_right_wheel_CTRLW0" -dv 1 -min 
		0 -at "double";
	setAttr -k on ".nds";
	setAttr -k off ".v";
	setAttr -k off ".tx";
	setAttr -k off ".ty";
	setAttr -k off ".tz";
	setAttr -k off ".rx";
	setAttr -k off ".ry";
	setAttr -k off ".rz";
	setAttr -k off ".sx";
	setAttr -k off ".sy";
	setAttr -k off ".sz";
	setAttr ".erp" yes;
	setAttr ".rst" -type "double3" 0 -35.999999999999993 0 ;
	setAttr -k on ".w0";
createNode joint -n "rear_left_mount_JNT" -p "vehicle_chassis_JNT";
	rename -uid "75849ACD-462F-95D4-49B4-0F9631081C9E";
	addAttr -ci true -sn "tcVehicleRole" -ln "tcVehicleRole" -dt "string";
	addAttr -ci true -sn "tcWheelId" -ln "tcWheelId" -dt "string";
	addAttr -ci true -sn "tcAxle" -ln "tcAxle" -dt "string";
	addAttr -ci true -sn "tcCollisionMask" -ln "tcCollisionMask" -dt "string";
	addAttr -ci true -k true -sn "tcRadiusM" -ln "tcRadiusM" -min 0 -at "double";
	addAttr -ci true -k true -sn "tcSuspensionRestLengthM" -ln "tcSuspensionRestLengthM" 
		-min 0 -at "double";
	addAttr -ci true -k true -sn "tcSuspensionTravelM" -ln "tcSuspensionTravelM" -min 
		0 -at "double";
	addAttr -ci true -k true -sn "tcSpringStiffness" -ln "tcSpringStiffness" -min 0 
		-at "double";
	addAttr -ci true -k true -sn "tcSpringDamping" -ln "tcSpringDamping" -min 0 -at "double";
	addAttr -ci true -k true -sn "tcBrakeTorqueNm" -ln "tcBrakeTorqueNm" -min 0 -at "double";
	addAttr -ci true -k true -sn "tcSteerable" -ln "tcSteerable" -min 0 -max 1 -at "bool";
	addAttr -ci true -k true -sn "tcDriven" -ln "tcDriven" -min 0 -max 1 -at "bool";
	addAttr -ci true -k true -sn "tcBraked" -ln "tcBraked" -min 0 -max 1 -at "bool";
	setAttr ".t" -type "double3" -80 5 -120 ;
	setAttr ".mnrl" -type "double3" -360 -360 -360 ;
	setAttr ".mxrl" -type "double3" 360 360 360 ;
	setAttr ".radi" 4;
	setAttr ".tcVehicleRole" -type "string" "wheel_mount";
	setAttr ".tcWheelId" -type "string" "rear_left";
	setAttr ".tcAxle" -type "string" "rear";
	setAttr ".tcCollisionMask" -type "string" "world_static";
	setAttr -k on ".tcRadiusM" 0.34;
	setAttr -k on ".tcSuspensionRestLengthM" 0.36;
	setAttr -k on ".tcSuspensionTravelM" 0.18;
	setAttr -k on ".tcSpringStiffness" 32000;
	setAttr -k on ".tcSpringDamping" 4200;
	setAttr -k on ".tcBrakeTorqueNm" 1800;
	setAttr -k on ".tcDriven" yes;
	setAttr -k on ".tcBraked" yes;
createNode joint -n "rear_left_wheel_JNT" -p "rear_left_mount_JNT";
	rename -uid "DA714C51-44A2-C15E-B59E-BAA1BF6270C4";
	addAttr -ci true -sn "tcVehicleRole" -ln "tcVehicleRole" -dt "string";
	addAttr -ci true -sn "tcWheelId" -ln "tcWheelId" -dt "string";
	setAttr ".mnrl" -type "double3" -360 -360 -360 ;
	setAttr ".mxrl" -type "double3" 360 360 360 ;
	setAttr ".radi" 5;
	setAttr ".tcVehicleRole" -type "string" "wheel";
	setAttr ".tcWheelId" -type "string" "rear_left";
createNode joint -n "rear_left_contact_JNT" -p "rear_left_wheel_JNT";
	rename -uid "EF8E6CD0-483C-CFFE-5C1B-D5A2B6B89719";
	addAttr -ci true -sn "tcVehicleRole" -ln "tcVehicleRole" -dt "string";
	addAttr -ci true -sn "tcWheelId" -ln "tcWheelId" -dt "string";
	setAttr ".t" -type "double3" 0 -34.000000000000014 0 ;
	setAttr ".mnrl" -type "double3" -360 -360 -360 ;
	setAttr ".mxrl" -type "double3" 360 360 360 ;
	setAttr ".radi" 2;
	setAttr ".tcVehicleRole" -type "string" "ground_contact";
	setAttr ".tcWheelId" -type "string" "rear_left";
createNode parentConstraint -n "rear_left_wheel_parentConstraint" -p "rear_left_wheel_JNT";
	rename -uid "B3315F9E-470F-7727-1928-C7ABFF247819";
	addAttr -dcb 0 -ci true -k true -sn "w0" -ln "rear_left_wheel_CTRLW0" -dv 1 -min 
		0 -at "double";
	setAttr -k on ".nds";
	setAttr -k off ".v";
	setAttr -k off ".tx";
	setAttr -k off ".ty";
	setAttr -k off ".tz";
	setAttr -k off ".rx";
	setAttr -k off ".ry";
	setAttr -k off ".rz";
	setAttr -k off ".sx";
	setAttr -k off ".sy";
	setAttr -k off ".sz";
	setAttr ".erp" yes;
	setAttr ".rst" -type "double3" 0 -35.999999999999993 0 ;
	setAttr -k on ".w0";
createNode joint -n "rear_right_mount_JNT" -p "vehicle_chassis_JNT";
	rename -uid "4E207CFD-4970-BA69-72FB-57B8E1060D14";
	addAttr -ci true -sn "tcVehicleRole" -ln "tcVehicleRole" -dt "string";
	addAttr -ci true -sn "tcWheelId" -ln "tcWheelId" -dt "string";
	addAttr -ci true -sn "tcAxle" -ln "tcAxle" -dt "string";
	addAttr -ci true -sn "tcCollisionMask" -ln "tcCollisionMask" -dt "string";
	addAttr -ci true -k true -sn "tcRadiusM" -ln "tcRadiusM" -min 0 -at "double";
	addAttr -ci true -k true -sn "tcSuspensionRestLengthM" -ln "tcSuspensionRestLengthM" 
		-min 0 -at "double";
	addAttr -ci true -k true -sn "tcSuspensionTravelM" -ln "tcSuspensionTravelM" -min 
		0 -at "double";
	addAttr -ci true -k true -sn "tcSpringStiffness" -ln "tcSpringStiffness" -min 0 
		-at "double";
	addAttr -ci true -k true -sn "tcSpringDamping" -ln "tcSpringDamping" -min 0 -at "double";
	addAttr -ci true -k true -sn "tcBrakeTorqueNm" -ln "tcBrakeTorqueNm" -min 0 -at "double";
	addAttr -ci true -k true -sn "tcSteerable" -ln "tcSteerable" -min 0 -max 1 -at "bool";
	addAttr -ci true -k true -sn "tcDriven" -ln "tcDriven" -min 0 -max 1 -at "bool";
	addAttr -ci true -k true -sn "tcBraked" -ln "tcBraked" -min 0 -max 1 -at "bool";
	setAttr ".t" -type "double3" 80 5 -120 ;
	setAttr ".mnrl" -type "double3" -360 -360 -360 ;
	setAttr ".mxrl" -type "double3" 360 360 360 ;
	setAttr ".radi" 4;
	setAttr ".tcVehicleRole" -type "string" "wheel_mount";
	setAttr ".tcWheelId" -type "string" "rear_right";
	setAttr ".tcAxle" -type "string" "rear";
	setAttr ".tcCollisionMask" -type "string" "world_static";
	setAttr -k on ".tcRadiusM" 0.34;
	setAttr -k on ".tcSuspensionRestLengthM" 0.36;
	setAttr -k on ".tcSuspensionTravelM" 0.18;
	setAttr -k on ".tcSpringStiffness" 32000;
	setAttr -k on ".tcSpringDamping" 4200;
	setAttr -k on ".tcBrakeTorqueNm" 1800;
	setAttr -k on ".tcDriven" yes;
	setAttr -k on ".tcBraked" yes;
createNode joint -n "rear_right_wheel_JNT" -p "rear_right_mount_JNT";
	rename -uid "DCAD8047-42CC-98EF-FCCE-88A633C7BCDF";
	addAttr -ci true -sn "tcVehicleRole" -ln "tcVehicleRole" -dt "string";
	addAttr -ci true -sn "tcWheelId" -ln "tcWheelId" -dt "string";
	setAttr ".mnrl" -type "double3" -360 -360 -360 ;
	setAttr ".mxrl" -type "double3" 360 360 360 ;
	setAttr ".radi" 5;
	setAttr ".tcVehicleRole" -type "string" "wheel";
	setAttr ".tcWheelId" -type "string" "rear_right";
createNode joint -n "rear_right_contact_JNT" -p "rear_right_wheel_JNT";
	rename -uid "A2031ED4-4940-89F9-8936-C898C22130E3";
	addAttr -ci true -sn "tcVehicleRole" -ln "tcVehicleRole" -dt "string";
	addAttr -ci true -sn "tcWheelId" -ln "tcWheelId" -dt "string";
	setAttr ".t" -type "double3" 0 -34.000000000000014 0 ;
	setAttr ".mnrl" -type "double3" -360 -360 -360 ;
	setAttr ".mxrl" -type "double3" 360 360 360 ;
	setAttr ".radi" 2;
	setAttr ".tcVehicleRole" -type "string" "ground_contact";
	setAttr ".tcWheelId" -type "string" "rear_right";
createNode parentConstraint -n "rear_right_wheel_parentConstraint" -p "rear_right_wheel_JNT";
	rename -uid "CF117275-4EC7-A6CA-1AF0-FAA55D7397FA";
	addAttr -dcb 0 -ci true -k true -sn "w0" -ln "rear_right_wheel_CTRLW0" -dv 1 -min 
		0 -at "double";
	setAttr -k on ".nds";
	setAttr -k off ".v";
	setAttr -k off ".tx";
	setAttr -k off ".ty";
	setAttr -k off ".tz";
	setAttr -k off ".rx";
	setAttr -k off ".ry";
	setAttr -k off ".rz";
	setAttr -k off ".sx";
	setAttr -k off ".sy";
	setAttr -k off ".sz";
	setAttr ".erp" yes;
	setAttr ".rst" -type "double3" 0 -35.999999999999993 0 ;
	setAttr -k on ".w0";
createNode parentConstraint -n "vehicle_chassis_parentConstraint" -p "vehicle_chassis_JNT";
	rename -uid "3AD4ABCE-4765-CB3C-4654-4CA91A50ADFB";
	addAttr -dcb 0 -ci true -k true -sn "w0" -ln "vehicle_chassis_CTRLW0" -dv 1 -min 
		0 -at "double";
	setAttr -k on ".nds";
	setAttr -k off ".v";
	setAttr -k off ".tx";
	setAttr -k off ".ty";
	setAttr -k off ".tz";
	setAttr -k off ".rx";
	setAttr -k off ".ry";
	setAttr -k off ".rz";
	setAttr -k off ".sx";
	setAttr -k off ".sy";
	setAttr -k off ".sz";
	setAttr ".erp" yes;
	setAttr ".rst" -type "double3" 0 65 0 ;
	setAttr -k on ".w0";
createNode parentConstraint -n "vehicle_root_parentConstraint" -p "vehicle_root_JNT";
	rename -uid "02D8E358-4016-0C0D-5C6F-16A9F8B5840B";
	addAttr -dcb 0 -ci true -k true -sn "w0" -ln "vehicle_global_CTRLW0" -dv 1 -min 
		0 -at "double";
	setAttr -k on ".nds";
	setAttr -k off ".v";
	setAttr -k off ".tx";
	setAttr -k off ".ty";
	setAttr -k off ".tz";
	setAttr -k off ".rx";
	setAttr -k off ".ry";
	setAttr -k off ".rz";
	setAttr -k off ".sx";
	setAttr -k off ".sy";
	setAttr -k off ".sz";
	setAttr ".erp" yes;
	setAttr -k on ".w0";
createNode transform -n "vehicle_RIG";
	rename -uid "8AED79A4-4DEA-8F07-0A02-F4A59CB65A0B";
	addAttr -ci true -sn "tcVehicleRigSchema" -ln "tcVehicleRigSchema" -dt "string";
	addAttr -ci true -sn "tcPortableRootJoint" -ln "tcPortableRootJoint" -dt "string";
	addAttr -ci true -sn "tcGroundMeshes" -ln "tcGroundMeshes" -dt "string";
	addAttr -ci true -k true -sn "groundDetection" -ln "groundDetection" -min 0 -max 
		1 -at "bool";
	addAttr -ci true -k true -sn "alignWheelsToGround" -ln "alignWheelsToGround" -min 
		0 -max 1 -at "bool";
	addAttr -ci true -k true -sn "liveGroundEvaluation" -ln "liveGroundEvaluation" -min 
		0 -max 1 -at "bool";
	addAttr -ci true -k true -sn "autoWheelSpin" -ln "autoWheelSpin" -min 0 -max 1 -at "bool";
	addAttr -ci true -k true -sn "debugGroundRays" -ln "debugGroundRays" -min 0 -max 
		1 -at "bool";
	addAttr -ci true -k true -sn "minimumGroundNormal" -ln "minimumGroundNormal" -min 
		0 -max 1 -at "double";
	addAttr -ci true -k true -sn "wheelRollMultiplier" -ln "wheelRollMultiplier" -at "double";
	addAttr -ci true -k true -sn "groundOffset" -ln "groundOffset" -at "double";
	addAttr -ci true -sn "tcGlobalControl" -ln "tcGlobalControl" -dt "string";
	addAttr -ci true -sn "tcChassisControl" -ln "tcChassisControl" -dt "string";
	addAttr -ci true -sn "tcAutoSteerInitialized" -ln "tcAutoSteerInitialized" -min 
		0 -max 1 -at "bool";
	addAttr -ci true -sn "tcAutoSteerPreviousX" -ln "tcAutoSteerPreviousX" -at "double";
	addAttr -ci true -sn "tcAutoSteerPreviousY" -ln "tcAutoSteerPreviousY" -at "double";
	addAttr -ci true -sn "tcAutoSteerPreviousZ" -ln "tcAutoSteerPreviousZ" -at "double";
	addAttr -ci true -sn "tcAutoSteerPreviousForwardX" -ln "tcAutoSteerPreviousForwardX" 
		-at "double";
	addAttr -ci true -sn "tcAutoSteerPreviousForwardY" -ln "tcAutoSteerPreviousForwardY" 
		-at "double";
	addAttr -ci true -sn "tcAutoSteerPreviousForwardZ" -ln "tcAutoSteerPreviousForwardZ" 
		-at "double";
	addAttr -ci true -sn "tcAutoSteerLastTime" -ln "tcAutoSteerLastTime" -at "double";
	addAttr -ci true -sn "tcDriveInitialized" -ln "tcDriveInitialized" -min 0 -max 1 
		-at "bool";
	addAttr -ci true -sn "tcDrivePreviousX" -ln "tcDrivePreviousX" -at "double";
	addAttr -ci true -sn "tcDrivePreviousY" -ln "tcDrivePreviousY" -at "double";
	addAttr -ci true -sn "tcDrivePreviousZ" -ln "tcDrivePreviousZ" -at "double";
	addAttr -ci true -sn "tcDrivePreviousYaw" -ln "tcDrivePreviousYaw" -at "double";
	addAttr -ci true -sn "tcDriveLastTime" -ln "tcDriveLastTime" -at "double";
	addAttr -ci true -sn "tcWheelRigMap" -ln "tcWheelRigMap" -dt "string";
	setAttr ".tcVehicleRigSchema" -type "string" "tech_connector.vehicle_rig.maya.v1";
	setAttr ".tcPortableRootJoint" -type "string" "|vehicle_root_JNT";
	setAttr ".tcGroundMeshes" -type "string" "[\"|vehicle_demo_ground_GEO|vehicle_demo_ground_GEOShape\"]";
	setAttr -k on ".groundDetection" yes;
	setAttr -k on ".alignWheelsToGround" yes;
	setAttr -k on ".autoWheelSpin" yes;
	setAttr -k on ".debugGroundRays" yes;
	setAttr -k on ".minimumGroundNormal" 0.15;
	setAttr -k on ".wheelRollMultiplier" 1;
	setAttr ".tcGlobalControl" -type "string" "vehicle_global_CTRL";
	setAttr ".tcChassisControl" -type "string" "vehicle_chassis_CTRL";
	setAttr ".tcAutoSteerInitialized" yes;
	setAttr ".tcAutoSteerPreviousY" 65;
	setAttr ".tcAutoSteerPreviousZ" -300;
	setAttr ".tcAutoSteerPreviousForwardZ" 1;
	setAttr ".tcAutoSteerLastTime" 1;
	setAttr ".tcDriveInitialized" yes;
	setAttr ".tcDrivePreviousZ" -300;
	setAttr ".tcDriveLastTime" 1;
	setAttr ".tcWheelRigMap" -type "string" (
		"[{\"axle\":\"front\",\"control\":\"front_left_wheel_CTRL\",\"ground_debug\":\"front_left_groundRay_DBG\",\"id\":\"front_left\",\"mount\":\"|vehicle_root_JNT|vehicle_chassis_JNT|front_left_mount_JNT\",\"side\":\"left\",\"spin_driver\":\"front_left_spin_DRV\",\"steer_driver\":\"front_left_steer_DRV\",\"suspension_driver\":\"front_left_suspension_DRV\",\"wheel_joint\":\"|vehicle_root_JNT|vehicle_chassis_JNT|front_left_mount_JNT|front_left_wheel_JNT\"},{\"axle\":\"front\",\"control\":\"front_right_wheel_CTRL\",\"ground_debug\":\"front_right_groundRay_DBG\",\"id\":\"front_right\",\"mount\":\"|vehicle_root_JNT|vehicle_chassis_JNT|front_right_mount_JNT\",\"side\":\"right\",\"spin_driver\":\"front_right_spin_DRV\",\"steer_driver\":\"front_right_steer_DRV\",\"suspension_driver\":\"front_right_suspension_DRV\",\"wheel_joint\":\"|vehicle_root_JNT|vehicle_chassis_JNT|front_right_mount_JNT|front_right_wheel_JNT\"},{\"axle\":\"rear\",\"control\":\"rear_left_wheel_CTRL\",\"ground_debug\":\"rear_left_groundRay_DBG\",\"id\":\"rear_left\",\"mount\":\"|vehicle_root_JNT|vehicle_chassis_JNT|rear_left_mount_JNT\",\"side\":\"left\",\"spin_driver\":\"rear_left_spin_DRV\",\"steer_driver\":\"rear_left_steer_DRV\",\"suspension_driver\":\"rear_left_suspension_DRV\",\"wheel_joint\":\"|vehicle_root_JNT|vehicle_chassis_JNT|rear_left_mount_JNT|rear_left_wheel_JNT\"},{\"axle\":\"rear\",\"control\":\"rear_right_wheel_CTRL\",\"ground_debug\":\"rear_right_groundRay_DBG\",\"id\":\"rear_right\",\"mount\":\"|vehicle_root_JNT|vehicle_chassis_JNT|rear_right_mount_JNT\",\"side\":\"right\",\"spin_driver\":\"rear_right_spin_DRV\",\"steer_driver\":\"rear_right_steer_DRV\",\"suspension_driver\":\"rear_right_suspension_DRV\",\"wheel_joint\":\"|vehicle_root_JNT|vehicle_chassis_JNT|rear_right_mount_JNT|rear_right_wheel_JNT\"}]");
createNode transform -n "vehicle_controls_GRP" -p "vehicle_RIG";
	rename -uid "A0DFBFED-4A37-8769-0D1A-D0A7D0B112BA";
createNode transform -n "vehicle_global_CTRL" -p "vehicle_controls_GRP";
	rename -uid "FC57A1DB-4954-F89E-EAD2-75B3281A1CD3";
createNode nurbsCurve -n "curveShape1" -p "vehicle_global_CTRL";
	rename -uid "C180996B-4F2B-E29D-0A14-C7A08A698CF2";
	setAttr -k off ".v";
	setAttr ".ove" yes;
	setAttr ".ovc" 14;
	setAttr ".cc" -type "nurbsCurve" 
		1 4 0 no 3
		5 0 1 2 3 4
		5
		-120 0 -168
		-120 0 168
		120 0 168
		120 0 -168
		-120 0 -168
		;
createNode transform -n "vehicle_chassis_CTRL" -p "vehicle_global_CTRL";
	rename -uid "413E5610-4D96-397D-BA97-D3AFAA754514";
	addAttr -ci true -k true -sn "steering" -ln "steering" -min -1 -max 1 -at "double";
	addAttr -ci true -k true -sn "throttle" -ln "throttle" -min -1 -max 1 -at "double";
	addAttr -ci true -k true -sn "brake" -ln "brake" -min 0 -max 1 -at "double";
	addAttr -ci true -k true -sn "maximumSteerAngle" -ln "maximumSteerAngle" -at "double";
	addAttr -ci true -k true -sn "ackermann" -ln "ackermann" -min 0 -max 1 -at "double";
	addAttr -ci true -k true -sn "autoSteering" -ln "autoSteering" -min 0 -max 1 -at "bool";
	addAttr -ci true -k true -sn "autoSteerBlend" -ln "autoSteerBlend" -min 0 -max 1 
		-at "double";
	addAttr -ci true -sn "autoSteerAngle" -ln "autoSteerAngle" -at "double";
	addAttr -ci true -k true -sn "steeringDrivesMotion" -ln "steeringDrivesMotion" -min 
		0 -max 1 -at "bool";
	setAttr ".t" -type "double3" 0 65 0 ;
	setAttr -k on ".steering";
	setAttr -k on ".maximumSteerAngle" 32;
	setAttr -k on ".ackermann" 1;
	setAttr -k on ".autoSteering" yes;
	setAttr -k on ".autoSteerBlend" 1;
	setAttr -k on ".steeringDrivesMotion" yes;
createNode nurbsCurve -n "curveShape2" -p "vehicle_chassis_CTRL";
	rename -uid "FCB2BBF8-4E17-7E11-64AB-59A5FAA58D47";
	setAttr -k off ".v";
	setAttr ".ove" yes;
	setAttr ".ovc" 17;
	setAttr ".cc" -type "nurbsCurve" 
		1 15 0 no 3
		16 0 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15
		16
		-92 -30 -150
		-92 -30 150
		92 -30 150
		92 -30 -150
		-92 -30 -150
		-92 30 -150
		-92 30 150
		92 30 150
		92 30 -150
		-92 30 -150
		-92 30 150
		-92 -30 150
		92 -30 150
		92 30 150
		92 30 -150
		92 -30 -150
		;
createNode transform -n "vehicle_solver_GRP" -p "vehicle_RIG";
	rename -uid "A55FECB8-4DAE-315B-03AD-9B8296F9CD1C";
createNode transform -n "front_left_suspension_DRV" -p "vehicle_solver_GRP";
	rename -uid "DBD6DD82-40A3-7C40-B8A5-2EA8FC2C2310";
createNode transform -n "front_left_steer_DRV" -p "front_left_suspension_DRV";
	rename -uid "42F5C0A3-441B-044D-743F-1F873B94B7C7";
	setAttr ".r" -type "double3" 0 0 0 ;
createNode transform -n "front_left_spin_DRV" -p "front_left_steer_DRV";
	rename -uid "9F1EC05D-4918-04F2-50D2-C09C113C378F";
	setAttr ".r" -type "double3" 0 0 0 ;
createNode transform -n "front_left_wheel_CTRL" -p "front_left_spin_DRV";
	rename -uid "7E161541-4BC6-4F18-9C59-95AF7BFA87D5";
	addAttr -ci true -k true -sn "spin" -ln "spin" -at "double";
	addAttr -ci true -sn "autoSpin" -ln "autoSpin" -at "double";
	addAttr -ci true -k true -sn "steerOffset" -ln "steerOffset" -min -90 -max 90 -at "double";
	addAttr -ci true -sn "grounded" -ln "grounded" -min 0 -max 1 -at "bool";
	addAttr -ci true -sn "suspensionCompression" -ln "suspensionCompression" -at "double";
	addAttr -ci true -sn "tcRollInitialized" -ln "tcRollInitialized" -min 0 -max 1 -at "bool";
	addAttr -ci true -sn "tcPreviousWorldX" -ln "tcPreviousWorldX" -at "double";
	addAttr -ci true -sn "tcPreviousWorldY" -ln "tcPreviousWorldY" -at "double";
	addAttr -ci true -sn "tcPreviousWorldZ" -ln "tcPreviousWorldZ" -at "double";
	addAttr -ci true -sn "tcPreviousForwardX" -ln "tcPreviousForwardX" -at "double";
	addAttr -ci true -sn "tcPreviousForwardY" -ln "tcPreviousForwardY" -at "double";
	addAttr -ci true -sn "tcPreviousForwardZ" -ln "tcPreviousForwardZ" -at "double";
	addAttr -ci true -sn "tcLastEvaluationTime" -ln "tcLastEvaluationTime" -at "double";
	addAttr -ci true -sn "tcWheelId" -ln "tcWheelId" -dt "string";
	setAttr ".grounded" yes;
	setAttr ".suspensionCompression" -0.038168794125039728;
	setAttr ".tcRollInitialized" yes;
	setAttr ".tcPreviousWorldX" -80;
	setAttr ".tcPreviousWorldY" 30.183120587496028;
	setAttr ".tcPreviousWorldZ" -180;
	setAttr ".tcPreviousForwardX" -0.001354783030231904;
	setAttr ".tcPreviousForwardY" -0.075611942423834608;
	setAttr ".tcPreviousForwardZ" 0.99713639925831399;
	setAttr ".tcLastEvaluationTime" 1;
	setAttr ".tcWheelId" -type "string" "front_left";
createNode nurbsCurve -n "front_left_wheel_CTRLShape" -p "front_left_wheel_CTRL";
	rename -uid "A7103807-4CCF-6202-8A9F-A2A0FA2D41FC";
	setAttr -k off ".v";
	setAttr ".ove" yes;
	setAttr ".ovc" 6;
	setAttr ".cc" -type "nurbsCurve" 
		3 16 2 no 3
		21 -2 -1 0 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18
		19
		8.8284603060805375e-16 34.808058324492706 -14.417969837878571
		5.4690819535088956e-31 37.675970837753646 -8.931688642499509e-15
		-8.8284603060805503e-16 34.808058324492706 14.417969837878593
		-1.6312867560752304e-15 26.640934467162214 26.640934467162218
		-2.1313788605812191e-15 14.417969837878589 34.808058324492713
		-2.3069878545612017e-15 -1.7379015688434388e-15 37.675970837753653
		-2.1313788605812183e-15 -14.417969837878591 34.808058324492698
		-1.6312867560752304e-15 -26.640934467162225 26.640934467162218
		-8.8284603060805474e-16 -34.808058324492713 14.417969837878587
		1.7433831420639737e-31 -37.675970837753646 -2.847160737737256e-15
		8.8284603060805553e-16 -34.808058324492706 -14.4179698378786
		1.6312867560752302e-15 -26.640934467162204 -26.640934467162214
		2.1313788605812194e-15 -14.417969837878582 -34.80805832449272
		2.3069878545612009e-15 6.4725436457779811e-15 -37.675970837753638
		2.1313788605812191e-15 14.417969837878603 -34.808058324492713
		1.6312867560752296e-15 26.640934467162221 -26.640934467162204
		8.8284603060805375e-16 34.808058324492706 -14.417969837878571
		5.4690819535088956e-31 37.675970837753646 -8.931688642499509e-15
		-8.8284603060805503e-16 34.808058324492706 14.417969837878593
		;
createNode transform -n "front_right_suspension_DRV" -p "vehicle_solver_GRP";
	rename -uid "C8D6E2AB-4B28-3E97-E314-8892289F449F";
createNode transform -n "front_right_steer_DRV" -p "front_right_suspension_DRV";
	rename -uid "59133140-433E-253E-A2CC-72B97F8EE502";
	setAttr ".r" -type "double3" 0 0 0 ;
createNode transform -n "front_right_spin_DRV" -p "front_right_steer_DRV";
	rename -uid "4B8EE7D2-45B6-9F90-49C2-3B82966CA455";
	setAttr ".r" -type "double3" 0 0 0 ;
createNode transform -n "front_right_wheel_CTRL" -p "front_right_spin_DRV";
	rename -uid "A8276BA9-4EA1-3625-7261-7E8B2B289D0C";
	addAttr -ci true -k true -sn "spin" -ln "spin" -at "double";
	addAttr -ci true -sn "autoSpin" -ln "autoSpin" -at "double";
	addAttr -ci true -k true -sn "steerOffset" -ln "steerOffset" -min -90 -max 90 -at "double";
	addAttr -ci true -sn "grounded" -ln "grounded" -min 0 -max 1 -at "bool";
	addAttr -ci true -sn "suspensionCompression" -ln "suspensionCompression" -at "double";
	addAttr -ci true -sn "tcRollInitialized" -ln "tcRollInitialized" -min 0 -max 1 -at "bool";
	addAttr -ci true -sn "tcPreviousWorldX" -ln "tcPreviousWorldX" -at "double";
	addAttr -ci true -sn "tcPreviousWorldY" -ln "tcPreviousWorldY" -at "double";
	addAttr -ci true -sn "tcPreviousWorldZ" -ln "tcPreviousWorldZ" -at "double";
	addAttr -ci true -sn "tcPreviousForwardX" -ln "tcPreviousForwardX" -at "double";
	addAttr -ci true -sn "tcPreviousForwardY" -ln "tcPreviousForwardY" -at "double";
	addAttr -ci true -sn "tcPreviousForwardZ" -ln "tcPreviousForwardZ" -at "double";
	addAttr -ci true -sn "tcLastEvaluationTime" -ln "tcLastEvaluationTime" -at "double";
	addAttr -ci true -sn "tcWheelId" -ln "tcWheelId" -dt "string";
	setAttr ".grounded" yes;
	setAttr ".suspensionCompression" -0.066875985228170343;
	setAttr ".tcRollInitialized" yes;
	setAttr ".tcPreviousWorldX" 80;
	setAttr ".tcPreviousWorldY" 27.312401477182966;
	setAttr ".tcPreviousWorldZ" -180;
	setAttr ".tcPreviousForwardX" -0.001344052645872607;
	setAttr ".tcPreviousForwardY" -0.075012826743322145;
	setAttr ".tcPreviousForwardZ" 0.99718166316196444;
	setAttr ".tcLastEvaluationTime" 1;
	setAttr ".tcWheelId" -type "string" "front_right";
createNode nurbsCurve -n "front_right_wheel_CTRLShape" -p "front_right_wheel_CTRL";
	rename -uid "6E51C056-48C8-712F-ACF4-AD89D026DF2F";
	setAttr -k off ".v";
	setAttr ".ove" yes;
	setAttr ".ovc" 13;
	setAttr ".cc" -type "nurbsCurve" 
		3 16 2 no 3
		21 -2 -1 0 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18
		19
		8.8284603060805375e-16 34.808058324492706 -14.417969837878571
		5.4690819535088956e-31 37.675970837753646 -8.931688642499509e-15
		-8.8284603060805503e-16 34.808058324492706 14.417969837878593
		-1.6312867560752304e-15 26.640934467162214 26.640934467162218
		-2.1313788605812191e-15 14.417969837878589 34.808058324492713
		-2.3069878545612017e-15 -1.7379015688434388e-15 37.675970837753653
		-2.1313788605812183e-15 -14.417969837878591 34.808058324492698
		-1.6312867560752304e-15 -26.640934467162225 26.640934467162218
		-8.8284603060805474e-16 -34.808058324492713 14.417969837878587
		1.7433831420639737e-31 -37.675970837753646 -2.847160737737256e-15
		8.8284603060805553e-16 -34.808058324492706 -14.4179698378786
		1.6312867560752302e-15 -26.640934467162204 -26.640934467162214
		2.1313788605812194e-15 -14.417969837878582 -34.80805832449272
		2.3069878545612009e-15 6.4725436457779811e-15 -37.675970837753638
		2.1313788605812191e-15 14.417969837878603 -34.808058324492713
		1.6312867560752296e-15 26.640934467162221 -26.640934467162204
		8.8284603060805375e-16 34.808058324492706 -14.417969837878571
		5.4690819535088956e-31 37.675970837753646 -8.931688642499509e-15
		-8.8284603060805503e-16 34.808058324492706 14.417969837878593
		;
createNode transform -n "rear_left_suspension_DRV" -p "vehicle_solver_GRP";
	rename -uid "5503E5D2-4AED-BFA5-3888-D5818ABBEE41";
createNode transform -n "rear_left_steer_DRV" -p "rear_left_suspension_DRV";
	rename -uid "3D3043BA-4655-2F84-7C51-1D911627A10A";
	setAttr ".r" -type "double3" 0 0 0 ;
createNode transform -n "rear_left_spin_DRV" -p "rear_left_steer_DRV";
	rename -uid "1746F788-4136-B6B2-8EEB-24A59E4C7525";
	setAttr ".r" -type "double3" 0 0 0 ;
createNode transform -n "rear_left_wheel_CTRL" -p "rear_left_spin_DRV";
	rename -uid "EDE719FA-405A-F99F-FDC4-60812469EDC7";
	addAttr -ci true -k true -sn "spin" -ln "spin" -at "double";
	addAttr -ci true -sn "autoSpin" -ln "autoSpin" -at "double";
	addAttr -ci true -k true -sn "steerOffset" -ln "steerOffset" -min -90 -max 90 -at "double";
	addAttr -ci true -sn "grounded" -ln "grounded" -min 0 -max 1 -at "bool";
	addAttr -ci true -sn "suspensionCompression" -ln "suspensionCompression" -at "double";
	addAttr -ci true -sn "tcRollInitialized" -ln "tcRollInitialized" -min 0 -max 1 -at "bool";
	addAttr -ci true -sn "tcPreviousWorldX" -ln "tcPreviousWorldX" -at "double";
	addAttr -ci true -sn "tcPreviousWorldY" -ln "tcPreviousWorldY" -at "double";
	addAttr -ci true -sn "tcPreviousWorldZ" -ln "tcPreviousWorldZ" -at "double";
	addAttr -ci true -sn "tcPreviousForwardX" -ln "tcPreviousForwardX" -at "double";
	addAttr -ci true -sn "tcPreviousForwardY" -ln "tcPreviousForwardY" -at "double";
	addAttr -ci true -sn "tcPreviousForwardZ" -ln "tcPreviousForwardZ" -at "double";
	addAttr -ci true -sn "tcLastEvaluationTime" -ln "tcLastEvaluationTime" -at "double";
	addAttr -ci true -sn "tcWheelId" -ln "tcWheelId" -dt "string";
	setAttr ".grounded" yes;
	setAttr ".suspensionCompression" 0.044916738756928469;
	setAttr ".tcRollInitialized" yes;
	setAttr ".tcPreviousWorldX" -80;
	setAttr ".tcPreviousWorldY" 38.491673875692847;
	setAttr ".tcPreviousWorldZ" -420;
	setAttr ".tcPreviousForwardX" -0.0009335542099113644;
	setAttr ".tcPreviousForwardY" 0.096179530635129254;
	setAttr ".tcPreviousForwardZ" 0.99536356491653011;
	setAttr ".tcLastEvaluationTime" 1;
	setAttr ".tcWheelId" -type "string" "rear_left";
createNode nurbsCurve -n "rear_left_wheel_CTRLShape" -p "rear_left_wheel_CTRL";
	rename -uid "D8EA3E30-49AD-8D4C-64B4-4B935D0CEF42";
	setAttr -k off ".v";
	setAttr ".ove" yes;
	setAttr ".ovc" 6;
	setAttr ".cc" -type "nurbsCurve" 
		3 16 2 no 3
		21 -2 -1 0 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18
		19
		8.8284603060805375e-16 34.808058324492706 -14.417969837878571
		5.4690819535088956e-31 37.675970837753646 -8.931688642499509e-15
		-8.8284603060805503e-16 34.808058324492706 14.417969837878593
		-1.6312867560752304e-15 26.640934467162214 26.640934467162218
		-2.1313788605812191e-15 14.417969837878589 34.808058324492713
		-2.3069878545612017e-15 -1.7379015688434388e-15 37.675970837753653
		-2.1313788605812183e-15 -14.417969837878591 34.808058324492698
		-1.6312867560752304e-15 -26.640934467162225 26.640934467162218
		-8.8284603060805474e-16 -34.808058324492713 14.417969837878587
		1.7433831420639737e-31 -37.675970837753646 -2.847160737737256e-15
		8.8284603060805553e-16 -34.808058324492706 -14.4179698378786
		1.6312867560752302e-15 -26.640934467162204 -26.640934467162214
		2.1313788605812194e-15 -14.417969837878582 -34.80805832449272
		2.3069878545612009e-15 6.4725436457779811e-15 -37.675970837753638
		2.1313788605812191e-15 14.417969837878603 -34.808058324492713
		1.6312867560752296e-15 26.640934467162221 -26.640934467162204
		8.8284603060805375e-16 34.808058324492706 -14.417969837878571
		5.4690819535088956e-31 37.675970837753646 -8.931688642499509e-15
		-8.8284603060805503e-16 34.808058324492706 14.417969837878593
		;
createNode transform -n "rear_right_suspension_DRV" -p "vehicle_solver_GRP";
	rename -uid "EE234C10-4E3C-14EE-864A-FCBEEC70C261";
createNode transform -n "rear_right_steer_DRV" -p "rear_right_suspension_DRV";
	rename -uid "814687C8-4430-57D2-BDB8-CBA354ED3701";
	setAttr ".r" -type "double3" 0 0 0 ;
createNode transform -n "rear_right_spin_DRV" -p "rear_right_steer_DRV";
	rename -uid "3ACFAB11-4899-EFD8-9C22-5BA593106FD1";
	setAttr ".r" -type "double3" 0 0 0 ;
createNode transform -n "rear_right_wheel_CTRL" -p "rear_right_spin_DRV";
	rename -uid "77177714-47C0-4C60-A5AD-05BFED5DEB32";
	addAttr -ci true -k true -sn "spin" -ln "spin" -at "double";
	addAttr -ci true -sn "autoSpin" -ln "autoSpin" -at "double";
	addAttr -ci true -k true -sn "steerOffset" -ln "steerOffset" -min -90 -max 90 -at "double";
	addAttr -ci true -sn "grounded" -ln "grounded" -min 0 -max 1 -at "bool";
	addAttr -ci true -sn "suspensionCompression" -ln "suspensionCompression" -at "double";
	addAttr -ci true -sn "tcRollInitialized" -ln "tcRollInitialized" -min 0 -max 1 -at "bool";
	addAttr -ci true -sn "tcPreviousWorldX" -ln "tcPreviousWorldX" -at "double";
	addAttr -ci true -sn "tcPreviousWorldY" -ln "tcPreviousWorldY" -at "double";
	addAttr -ci true -sn "tcPreviousWorldZ" -ln "tcPreviousWorldZ" -at "double";
	addAttr -ci true -sn "tcPreviousForwardX" -ln "tcPreviousForwardX" -at "double";
	addAttr -ci true -sn "tcPreviousForwardY" -ln "tcPreviousForwardY" -at "double";
	addAttr -ci true -sn "tcPreviousForwardZ" -ln "tcPreviousForwardZ" -at "double";
	addAttr -ci true -sn "tcLastEvaluationTime" -ln "tcLastEvaluationTime" -at "double";
	addAttr -ci true -sn "tcWheelId" -ln "tcWheelId" -dt "string";
	setAttr ".grounded" yes;
	setAttr ".suspensionCompression" 0.0584036198363043;
	setAttr ".tcRollInitialized" yes;
	setAttr ".tcPreviousWorldX" 80;
	setAttr ".tcPreviousWorldY" 39.84036198363043;
	setAttr ".tcPreviousWorldZ" -420;
	setAttr ".tcPreviousForwardX" -0.00077597819306187582;
	setAttr ".tcPreviousForwardY" 0.079945877683232289;
	setAttr ".tcPreviousForwardZ" 0.9967989037410212;
	setAttr ".tcLastEvaluationTime" 1;
	setAttr ".tcWheelId" -type "string" "rear_right";
createNode nurbsCurve -n "rear_right_wheel_CTRLShape" -p "rear_right_wheel_CTRL";
	rename -uid "83A13929-4B3C-DD7B-BB71-489F4D11A8F8";
	setAttr -k off ".v";
	setAttr ".ove" yes;
	setAttr ".ovc" 13;
	setAttr ".cc" -type "nurbsCurve" 
		3 16 2 no 3
		21 -2 -1 0 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18
		19
		8.8284603060805375e-16 34.808058324492706 -14.417969837878571
		5.4690819535088956e-31 37.675970837753646 -8.931688642499509e-15
		-8.8284603060805503e-16 34.808058324492706 14.417969837878593
		-1.6312867560752304e-15 26.640934467162214 26.640934467162218
		-2.1313788605812191e-15 14.417969837878589 34.808058324492713
		-2.3069878545612017e-15 -1.7379015688434388e-15 37.675970837753653
		-2.1313788605812183e-15 -14.417969837878591 34.808058324492698
		-1.6312867560752304e-15 -26.640934467162225 26.640934467162218
		-8.8284603060805474e-16 -34.808058324492713 14.417969837878587
		1.7433831420639737e-31 -37.675970837753646 -2.847160737737256e-15
		8.8284603060805553e-16 -34.808058324492706 -14.4179698378786
		1.6312867560752302e-15 -26.640934467162204 -26.640934467162214
		2.1313788605812194e-15 -14.417969837878582 -34.80805832449272
		2.3069878545612009e-15 6.4725436457779811e-15 -37.675970837753638
		2.1313788605812191e-15 14.417969837878603 -34.808058324492713
		1.6312867560752296e-15 26.640934467162221 -26.640934467162204
		8.8284603060805375e-16 34.808058324492706 -14.417969837878571
		5.4690819535088956e-31 37.675970837753646 -8.931688642499509e-15
		-8.8284603060805503e-16 34.808058324492706 14.417969837878593
		;
createNode transform -n "vehicle_ground_debug_GRP" -p "vehicle_RIG";
	rename -uid "C43AB780-4699-00B8-8426-B28CEFDAD165";
createNode transform -n "front_left_groundRay_DBG" -p "vehicle_ground_debug_GRP";
	rename -uid "38EFC4CE-445E-0C51-A9A8-2F83284849AF";
createNode nurbsCurve -n "curveShape3" -p "front_left_groundRay_DBG";
	rename -uid "04006CBA-4D14-B403-3B5B-A7944E6E47E9";
	setAttr -k off ".v";
	setAttr ".ove" yes;
	setAttr ".ovc" 14;
	setAttr ".cc" -type "nurbsCurve" 
		1 1 0 no 3
		2 0 1
		2
		-80 52 -180
		-80 -3.9199936389923096 -180
		;
createNode transform -n "front_right_groundRay_DBG" -p "vehicle_ground_debug_GRP";
	rename -uid "2FE6D5B6-48F5-5951-441B-4E8AE84B0864";
createNode nurbsCurve -n "curveShape4" -p "front_right_groundRay_DBG";
	rename -uid "F33BFB24-4045-0750-F1CD-5C9CAF4145D6";
	setAttr -k off ".v";
	setAttr ".ove" yes;
	setAttr ".ovc" 14;
	setAttr ".cc" -type "nurbsCurve" 
		1 1 0 no 3
		2 0 1
		2
		80 52 -180
		80 -6.7891645431518555 -180
		;
createNode transform -n "rear_left_groundRay_DBG" -p "vehicle_ground_debug_GRP";
	rename -uid "7A4EFAD8-4DF5-A87A-B135-4AA5CAC6A684";
createNode nurbsCurve -n "curveShape5" -p "rear_left_groundRay_DBG";
	rename -uid "1779E7FA-4E57-162E-2D0B-3E94BA49214B";
	setAttr -k off ".v";
	setAttr ".ove" yes;
	setAttr ".ovc" 14;
	setAttr ".cc" -type "nurbsCurve" 
		1 1 0 no 3
		2 0 1
		2
		-80 52 -420
		-80 4.331690788269043 -420
		;
createNode transform -n "rear_right_groundRay_DBG" -p "vehicle_ground_debug_GRP";
	rename -uid "2CB3802E-4EC2-0976-AF31-46BE755009BF";
createNode nurbsCurve -n "curveShape6" -p "rear_right_groundRay_DBG";
	rename -uid "BDC11951-4E8F-47ED-07D9-77B6E576DB1C";
	setAttr -k off ".v";
	setAttr ".ove" yes;
	setAttr ".ovc" 14;
	setAttr ".cc" -type "nurbsCurve" 
		1 1 0 no 3
		2 0 1
		2
		80 52 -420
		80 5.7295703887939453 -420
		;
createNode transform -n "vehicle_preview_geo_GRP" -p "vehicle_RIG";
	rename -uid "FFC5DD13-4711-3A75-813C-E58EF371A86B";
createNode transform -n "front_left_preview_GEO" -p "vehicle_preview_geo_GRP";
	rename -uid "681A3C13-42D0-A73E-9DAA-F28F414CFB1D";
createNode mesh -n "front_left_preview_GEOShape" -p "front_left_preview_GEO";
	rename -uid "A97F7D59-4F01-E0B9-36D3-9DAFC81FAC4B";
	setAttr -k off ".v";
	setAttr ".vir" yes;
	setAttr ".vif" yes;
	setAttr ".uvst[0].uvsn" -type "string" "map1";
	setAttr ".cuvs" -type "string" "map1";
	setAttr ".dcc" -type "string" "Diffuse";
	setAttr ".covm[0]"  0 1 1;
	setAttr ".cdvm[0]"  0 1 1;
	setAttr ".ndt" 0;
createNode parentConstraint -n "front_left_preview_GEO_parentConstraint1" -p "front_left_preview_GEO";
	rename -uid "08F5D9C7-4368-65AC-5951-719787FF0BC1";
	addAttr -dcb 0 -ci true -k true -sn "w0" -ln "front_left_wheel_JNTW0" -dv 1 -min 
		0 -at "double";
	setAttr -k on ".nds";
	setAttr -k off ".v";
	setAttr -k off ".tx";
	setAttr -k off ".ty";
	setAttr -k off ".tz";
	setAttr -k off ".rx";
	setAttr -k off ".ry";
	setAttr -k off ".rz";
	setAttr -k off ".sx";
	setAttr -k off ".sy";
	setAttr -k off ".sz";
	setAttr ".erp" yes;
	setAttr ".rst" -type "double3" -80 34.000000000000007 120 ;
	setAttr -k on ".w0";
createNode transform -n "front_right_preview_GEO" -p "vehicle_preview_geo_GRP";
	rename -uid "2330F209-4F13-D4C7-FAAC-758D63A79A78";
createNode mesh -n "front_right_preview_GEOShape" -p "front_right_preview_GEO";
	rename -uid "D4729AC0-4C42-ED74-F6B2-55BAC598E1DB";
	setAttr -k off ".v";
	setAttr ".vir" yes;
	setAttr ".vif" yes;
	setAttr ".uvst[0].uvsn" -type "string" "map1";
	setAttr ".cuvs" -type "string" "map1";
	setAttr ".dcc" -type "string" "Diffuse";
	setAttr ".covm[0]"  0 1 1;
	setAttr ".cdvm[0]"  0 1 1;
	setAttr ".ndt" 0;
createNode parentConstraint -n "front_right_preview_GEO_parentConstraint1" -p "front_right_preview_GEO";
	rename -uid "A4631A85-42CC-1476-D7F9-5CA0ADF22CA9";
	addAttr -dcb 0 -ci true -k true -sn "w0" -ln "front_right_wheel_JNTW0" -dv 1 -min 
		0 -at "double";
	setAttr -k on ".nds";
	setAttr -k off ".v";
	setAttr -k off ".tx";
	setAttr -k off ".ty";
	setAttr -k off ".tz";
	setAttr -k off ".rx";
	setAttr -k off ".ry";
	setAttr -k off ".rz";
	setAttr -k off ".sx";
	setAttr -k off ".sy";
	setAttr -k off ".sz";
	setAttr ".erp" yes;
	setAttr ".rst" -type "double3" 80 34.000000000000007 120 ;
	setAttr -k on ".w0";
createNode transform -n "rear_left_preview_GEO" -p "vehicle_preview_geo_GRP";
	rename -uid "17B38395-41F0-A0ED-E633-898F7743DDDD";
createNode mesh -n "rear_left_preview_GEOShape" -p "rear_left_preview_GEO";
	rename -uid "5069FB73-4C28-175C-AB8C-55B624D5A518";
	setAttr -k off ".v";
	setAttr ".vir" yes;
	setAttr ".vif" yes;
	setAttr ".uvst[0].uvsn" -type "string" "map1";
	setAttr ".cuvs" -type "string" "map1";
	setAttr ".dcc" -type "string" "Diffuse";
	setAttr ".covm[0]"  0 1 1;
	setAttr ".cdvm[0]"  0 1 1;
	setAttr ".ndt" 0;
createNode parentConstraint -n "rear_left_preview_GEO_parentConstraint1" -p "rear_left_preview_GEO";
	rename -uid "984C4DA6-4073-5B94-6C4F-0EA23EF61235";
	addAttr -dcb 0 -ci true -k true -sn "w0" -ln "rear_left_wheel_JNTW0" -dv 1 -min 
		0 -at "double";
	setAttr -k on ".nds";
	setAttr -k off ".v";
	setAttr -k off ".tx";
	setAttr -k off ".ty";
	setAttr -k off ".tz";
	setAttr -k off ".rx";
	setAttr -k off ".ry";
	setAttr -k off ".rz";
	setAttr -k off ".sx";
	setAttr -k off ".sy";
	setAttr -k off ".sz";
	setAttr ".erp" yes;
	setAttr ".rst" -type "double3" -80 34.000000000000007 -120 ;
	setAttr -k on ".w0";
createNode transform -n "rear_right_preview_GEO" -p "vehicle_preview_geo_GRP";
	rename -uid "5FC1F1FF-49CF-BE69-AB12-EA8622658CF1";
createNode mesh -n "rear_right_preview_GEOShape" -p "rear_right_preview_GEO";
	rename -uid "CE0F8D52-48F6-8185-7D4A-9F8BB5CBB3DB";
	setAttr -k off ".v";
	setAttr ".vir" yes;
	setAttr ".vif" yes;
	setAttr ".uvst[0].uvsn" -type "string" "map1";
	setAttr ".cuvs" -type "string" "map1";
	setAttr ".dcc" -type "string" "Diffuse";
	setAttr ".covm[0]"  0 1 1;
	setAttr ".cdvm[0]"  0 1 1;
	setAttr ".ndt" 0;
createNode parentConstraint -n "rear_right_preview_GEO_parentConstraint1" -p "rear_right_preview_GEO";
	rename -uid "FD4EA432-4137-EB03-CCFB-07A424410D95";
	addAttr -dcb 0 -ci true -k true -sn "w0" -ln "rear_right_wheel_JNTW0" -dv 1 -min 
		0 -at "double";
	setAttr -k on ".nds";
	setAttr -k off ".v";
	setAttr -k off ".tx";
	setAttr -k off ".ty";
	setAttr -k off ".tz";
	setAttr -k off ".rx";
	setAttr -k off ".ry";
	setAttr -k off ".rz";
	setAttr -k off ".sx";
	setAttr -k off ".sy";
	setAttr -k off ".sz";
	setAttr ".erp" yes;
	setAttr ".rst" -type "double3" 80 34.000000000000007 -120 ;
	setAttr -k on ".w0";
createNode transform -n "vehicle_chassis_preview_GEO" -p "vehicle_preview_geo_GRP";
	rename -uid "8EEF5050-4298-177A-DE52-0C9C7E3E1D3F";
createNode mesh -n "vehicle_chassis_preview_GEOShape" -p "vehicle_chassis_preview_GEO";
	rename -uid "619CAE3E-4A18-7967-C042-578435D81F51";
	setAttr -k off ".v";
	setAttr ".vir" yes;
	setAttr ".vif" yes;
	setAttr ".uvst[0].uvsn" -type "string" "map1";
	setAttr ".cuvs" -type "string" "map1";
	setAttr ".dcc" -type "string" "Diffuse";
	setAttr ".covm[0]"  0 1 1;
	setAttr ".cdvm[0]"  0 1 1;
	setAttr ".ndt" 0;
createNode parentConstraint -n "vehicle_chassis_preview_GEO_parentConstraint1" -p
		 "vehicle_chassis_preview_GEO";
	rename -uid "EAC9DE75-4744-FA24-9AD9-98A9BF8B8F8A";
	addAttr -dcb 0 -ci true -k true -sn "w0" -ln "vehicle_chassis_JNTW0" -dv 1 -min 
		0 -at "double";
	setAttr -k on ".nds";
	setAttr -k off ".v";
	setAttr -k off ".tx";
	setAttr -k off ".ty";
	setAttr -k off ".tz";
	setAttr -k off ".rx";
	setAttr -k off ".ry";
	setAttr -k off ".rz";
	setAttr -k off ".sx";
	setAttr -k off ".sy";
	setAttr -k off ".sz";
	setAttr ".erp" yes;
	setAttr ".rst" -type "double3" 0 65 0 ;
	setAttr -k on ".w0";
createNode transform -n "vehicle_demo_ground_GEO";
	rename -uid "8324D2DB-44AA-D4CC-6AEB-24B53274584A";
createNode mesh -n "vehicle_demo_ground_GEOShape" -p "vehicle_demo_ground_GEO";
	rename -uid "C32A5F81-4FEA-088C-D475-8E8B8A1818C3";
	setAttr -k off ".v";
	setAttr ".vir" yes;
	setAttr ".vif" yes;
	setAttr ".uvst[0].uvsn" -type "string" "map1";
	setAttr ".cuvs" -type "string" "map1";
	setAttr ".dcc" -type "string" "Diffuse";
	setAttr ".covm[0]"  0 1 1;
	setAttr ".cdvm[0]"  0 1 1;
	setAttr -s 1225 ".pt";
	setAttr ".pt[0:165]" -type "float3"  0 11.401727 0 0 10.701017 0 0 10.000307 
		0 0 9.2995977 0 0 8.5988874 0 0 7.8981781 0 0 7.1974683 0 0 6.4967585 0 0 5.7960486 
		0 0 5.0953393 0 0 4.394629 0 0 3.6939194 0 0 2.9932098 0 0 2.2924998 0 0 1.5917896 
		0 0 0.8910805 0 0 0.19037041 0 0 -0.51033968 0 0 -1.2110488 0 0 -1.9117589 0 0 -2.612469 
		0 0 -3.3131781 0 0 -4.0138884 0 0 -4.7145982 0 0 -5.4153075 0 0 8.5368271 0 0 7.8957624 
		0 0 7.2546978 0 0 6.6136336 0 0 5.972569 0 0 5.3315043 0 0 4.6904402 0 0 4.0493755 
		0 0 3.4083111 0 0 2.767247 0 0 2.1261823 0 0 1.485118 0 0 0.84405375 0 0 0.20298898 
		0 0 -0.43807575 0 0 -1.0791396 0 0 -1.7202042 0 0 -2.361269 0 0 -3.0023329 0 0 -3.6433976 
		0 0 -4.2844625 0 0 -4.9255261 0 0 -5.5665908 0 0 -6.2076554 0 0 -6.8487191 0 0 5.3554435 
		0 0 4.7950063 0 0 4.2345681 0 0 3.6741304 0 0 3.1136925 0 0 2.5532548 0 0 1.9928173 
		0 0 1.4323792 0 0 0.87194163 0 0 0.31150404 0 0 -0.24893397 0 0 -0.80937159 0 0 -1.3698092 
		0 0 -1.9302472 0 0 -2.4906852 0 0 -3.0511224 0 0 -3.6115603 0 0 -4.1719985 0 0 -4.7324357 
		0 0 -5.2928734 0 0 -5.8533115 0 0 -6.4137487 0 0 -6.9741869 0 0 -7.5346246 0 0 -8.0950623 
		0 0 2.0589619 0 0 1.5974936 0 0 1.1360251 0 0 0.67455691 0 0 0.21308838 0 0 -0.24837983 
		0 0 -0.70984805 0 0 -1.1713166 0 0 -1.6327847 0 0 -2.0942531 0 0 -2.5557215 0 0 -3.0171897 
		0 0 -3.478658 0 0 -3.9401264 0 0 -4.4015951 0 0 -4.8630629 0 0 -5.3245316 0 0 -5.7859998 
		0 0 -6.247468 0 0 -6.7089362 0 0 -7.1704049 0 0 -7.6318727 0 0 -8.0933409 0 0 -8.5548096 
		0 0 -9.0162773 0 0 -1.1520675 0 0 -1.4994628 0 0 -1.8468585 0 0 -2.1942539 0 0 -2.5416496 
		0 0 -2.8890448 0 0 -3.2364402 0 0 -3.5838358 0 0 -3.9312313 0 0 -4.2786264 0 0 -4.6260223 
		0 0 -4.9734178 0 0 -5.3208127 0 0 -5.6682086 0 0 -6.015604 0 0 -6.3629994 0 0 -6.7103949 
		0 0 -7.0577903 0 0 -7.4051857 0 0 -7.7525811 0 0 -8.0999765 0 0 -8.4473724 0 0 -8.7947674 
		0 0 -9.1421633 0 0 -9.4895582 0 0 -4.0916123 0 0 -4.3135648 0 0 -4.5355177 0 0 -4.7574701 
		0 0 -4.979423 0 0 -5.2013755 0 0 -5.4233284 0 0 -5.6452808 0 0 -5.8672338 0 0 -6.0891862 
		0 0 -6.3111391 0 0 -6.5330915 0 0 -6.755044 0 0 -6.9769969 0 0 -7.1989498 0 0 -7.4209023 
		0 0 -7.6428547 0 0 -7.8648076 0 0 -8.0867596 0 0 -8.308713 0 0 -8.5306654 0 0 -8.7526178 
		0 0 -8.9745703 0 0 -9.1965237 0 0 -9.4184761 0 0 -6.6004457 0 0 -6.6896911 0 0 -6.7789369 
		0 0 -6.8681827 0 0 -6.9574285 0 0 -7.0466743 0 0 -7.13592 0 0 -7.2251658 0 0 -7.3144112 
		0 0 -7.403657 0 0 -7.4929028 0 0 -7.5821486 0 0 -7.6713943 0 0 -7.7606401 0 0 -7.8498859 
		0 0 -7.9391313 0;
	setAttr ".pt[166:331]" 0 -8.0283775 0 0 -8.1176233 0 0 -8.2068682 0 0 -8.296114 
		0 0 -8.3853598 0 0 -8.4746056 0 0 -8.5638514 0 0 -8.6530972 0 0 -8.7423429 0 0 -8.556201 
		0 0 -8.509819 0 0 -8.4634361 0 0 -8.4170542 0 0 -8.3706722 0 0 -8.3242893 0 0 -8.2779074 
		0 0 -8.2315245 0 0 -8.1851425 0 0 -8.1387606 0 0 -8.0923777 0 0 -8.0459957 0 0 -7.9996133 
		0 0 -7.9532309 0 0 -7.9068484 0 0 -7.8604665 0 0 -7.8140841 0 0 -7.7677016 0 0 -7.7213192 
		0 0 -7.6749368 0 0 -7.6285543 0 0 -7.5821724 0 0 -7.53579 0 0 -7.4894075 0 0 -7.4430251 
		0 0 -9.8804445 0 0 -9.6999521 0 0 -9.5194597 0 0 -9.3389673 0 0 -9.1584749 0 0 -8.9779825 
		0 0 -8.7974901 0 0 -8.6169977 0 0 -8.4365053 0 0 -8.2560129 0 0 -8.0755205 0 0 -7.8950286 
		0 0 -7.7145362 0 0 -7.5340438 0 0 -7.3535514 0 0 -7.1730595 0 0 -6.9925671 0 0 -6.8120747 
		0 0 -6.6315823 0 0 -6.4510899 0 0 -6.2705975 0 0 -6.0901055 0 0 -5.9096131 0 0 -5.7291207 
		0 0 -5.5486283 0 0 -10.542358 0 0 -10.233664 0 0 -9.9249687 0 0 -9.6162739 0 0 -9.307579 
		0 0 -8.9988842 0 0 -8.6901894 0 0 -8.3814945 0 0 -8.0727997 0 0 -7.7641053 0 0 -7.4554105 
		0 0 -7.1467156 0 0 -6.8380208 0 0 -6.529326 0 0 -6.2206311 0 0 -5.9119363 0 0 -5.6032414 
		0 0 -5.2945466 0 0 -4.9858522 0 0 -4.6771574 0 0 -4.3684621 0 0 -4.0597677 0 0 -3.7510729 
		0 0 -3.4423778 0 0 -3.1336834 0 0 -10.558792 0 0 -10.131998 0 0 -9.705204 0 0 -9.27841 
		0 0 -8.8516159 0 0 -8.4248219 0 0 -7.9980278 0 0 -7.5712333 0 0 -7.1444392 0 0 -6.7176452 
		0 0 -6.2908511 0 0 -5.8640571 0 0 -5.437263 0 0 -5.0104685 0 0 -4.583674 0 0 -4.1568804 
		0 0 -3.7300861 0 0 -3.3032918 0 0 -2.876498 0 0 -2.4497037 0 0 -2.0229094 0 0 -1.5961156 
		0 0 -1.1693213 0 0 -0.74252695 0 0 -0.31573325 0 0 -9.9907522 0 0 -9.4598274 0 0 
		-8.9289017 0 0 -8.3979769 0 0 -7.8670521 0 0 -7.3361273 0 0 -6.8052025 0 0 -6.2742777 
		0 0 -5.7433529 0 0 -5.2124281 0 0 -4.6815028 0 0 -4.150578 0 0 -3.6196532 0 0 -3.0887282 
		0 0 -2.5578029 0 0 -2.0268786 0 0 -1.4959534 0 0 -0.96502835 0 0 -0.43410397 0 0 
		0.096821189 0 0 0.62774634 0 0 1.1586707 0 0 1.6895958 0 0 2.220521 0 0 2.7514453 
		0 0 -8.9366894 0 0 -8.3190107 0 0 -7.7013321 0 0 -7.083653 0 0 -6.4659739 0 0 -5.8482952 
		0 0 -5.2306166 0 0 -4.6129375 0 0 -3.9952588 0 0 -3.3775802 0 0 -2.759901 0 0 -2.1422224 
		0 0 -1.5245438 0 0 -0.90686458 0 0 -0.28918543 0 0 0.32849279 0 0 0.94617194 0 0 
		1.5638511 0 0 2.1815293 0 0 2.7992084 0 0 3.4168875 0 0 4.0345659 0 0 4.652245 0 
		0 5.2699242 0 0 5.8876023 0 0 -7.5231533 0 0 -6.8389363 0 0 -6.1547194 0 0 -5.4705024 
		0 0 -4.7862854 0 0 -4.1020689 0 0 -3.4178519 0;
	setAttr ".pt[332:497]" 0 -2.7336349 0 0 -2.0494182 0 0 -1.3652015 0 0 -0.68098432 
		0 0 0.003232334 0 0 0.68744898 0 0 1.3716662 0 0 2.0558834 0 0 2.7400994 0 0 3.4243166 
		0 0 4.1085339 0 0 4.7927499 0 0 5.4769673 0 0 6.1611843 0 0 6.8454003 0 0 7.5296178 
		0 0 8.2138348 0 0 8.8980513 0 0 -5.8935943 0 0 -5.1652336 0 0 -4.436872 0 0 -3.7085114 
		0 0 -2.98015 0 0 -2.2517891 0 0 -1.5234283 0 0 -0.79506689 0 0 -0.066706017 0 0 0.66165483 
		0 0 1.3900162 0 0 2.1183772 0 0 2.8467379 0 0 3.5750995 0 0 4.3034606 0 0 5.0318213 
		0 0 5.7601824 0 0 6.488544 0 0 7.2169042 0 0 7.9452658 0 0 8.6736269 0 0 9.4019871 
		0 0 10.130349 0 0 10.85871 0 0 11.58707 0 0 -4.1962223 0 0 -3.4475558 0 0 -2.6988888 
		0 0 -1.9502224 0 0 -1.2015554 0 0 -0.45288897 0 0 0.29577747 0 0 1.0444444 0 0 1.7931108 
		0 0 2.5417774 0 0 3.2904444 0 0 4.0391107 0 0 4.7877769 0 0 5.5364442 0 0 6.285111 
		0 0 7.0337772 0 0 7.782444 0 0 8.5311108 0 0 9.2797766 0 0 10.028444 0 0 10.777111 
		0 0 11.525777 0 0 12.274444 0 0 13.02311 0 0 13.771776 0 0 -2.5718675 0 0 -1.8273987 
		0 0 -1.0829293 0 0 -0.33846033 0 0 0.40600908 0 0 1.150478 0 0 1.8949468 0 0 2.6394162 
		0 0 3.3838851 0 0 4.1283541 0 0 4.8728232 0 0 5.6172924 0 0 6.3617611 0 0 7.1062307 
		0 0 7.8506999 0 0 8.5951681 0 0 9.3396378 0 0 10.084107 0 0 10.828575 0 0 11.573045 
		0 0 12.317514 0 0 13.061982 0 0 13.806452 0 0 14.550921 0 0 15.29539 0 0 -1.1428518 
		0 0 -0.42694637 0 0 0.28895965 0 0 1.0048652 0 0 1.7207712 0 0 2.4366767 0 0 3.1525822 
		0 0 3.8684883 0 0 4.5843935 0 0 5.3002992 0 0 6.0162053 0 0 6.7321105 0 0 7.4480162 
		0 0 8.1639223 0 0 8.8798285 0 0 9.5957336 0 0 10.311639 0 0 11.027545 0 0 11.74345 
		0 0 12.459356 0 0 13.175262 0 0 13.891168 0 0 14.607073 0 0 15.322979 0 0 16.038885 
		0 0 -0.0036735535 0 0 0.66023773 0 0 1.3241495 0 0 1.9880607 0 0 2.6519725 0 0 3.3158839 
		0 0 3.979795 0 0 4.6437068 0 0 5.3076181 0 0 5.9715295 0 0 6.6354413 0 0 7.2993522 
		0 0 7.9632635 0 0 8.6271753 0 0 9.2910872 0 0 9.954998 0 0 10.61891 0 0 11.282822 
		0 0 11.946733 0 0 12.610644 0 0 13.274556 0 0 13.938467 0 0 14.602378 0 0 15.26629 
		0 0 15.930201 0 0 0.78574824 0 0 1.375936 0 0 1.9661242 0 0 2.5563121 0 0 3.1465001 
		0 0 3.7366879 0 0 4.3268757 0 0 4.9170637 0 0 5.5072517 0 0 6.0974393 0 0 6.6876278 
		0 0 7.2778153 0 0 7.8680029 0 0 8.4581909 0 0 9.0483799 0 0 9.638567 0 0 10.228755 
		0 0 10.818943 0 0 11.40913 0 0 11.999319 0 0 12.589507 0 0 13.179694 0 0 13.769882 
		0;
	setAttr ".pt[498:663]" 0 14.36007 0 0 14.950258 0 0 1.20376 0 0 1.7009079 
		0 0 2.1980562 0 0 2.6952043 0 0 3.1923525 0 0 3.6895003 0 0 4.1866484 0 0 4.6837964 
		0 0 5.1809444 0 0 5.6780925 0 0 6.175241 0 0 6.6723886 0 0 7.1695366 0 0 7.6666851 
		0 0 8.1638336 0 0 8.6609812 0 0 9.1581287 0 0 9.6552773 0 0 10.152425 0 0 10.649573 
		0 0 11.146722 0 0 11.643869 0 0 12.141017 0 0 12.638165 0 0 13.135313 0 0 1.2673689 
		0 0 1.655206 0 0 2.0430434 0 0 2.4308803 0 0 2.8187177 0 0 3.2065549 0 0 3.5943918 
		0 0 3.9822292 0 0 4.3700662 0 0 4.7579036 0 0 5.1457405 0 0 5.5335779 0 0 5.9214149 
		0 0 6.3092523 0 0 6.6970897 0 0 7.0849261 0 0 7.4727635 0 0 7.8606009 0 0 8.2484379 
		0 0 8.6362753 0 0 9.0241127 0 0 9.4119492 0 0 9.7997866 0 0 10.187624 0 0 10.57546 
		0 0 1.0293316 0 0 1.2951641 0 0 1.5609968 0 0 1.8268292 0 0 2.0926619 0 0 2.3584943 
		0 0 2.6243269 0 0 2.8901596 0 0 3.155992 0 0 3.4218245 0 0 3.6876571 0 0 3.9534898 
		0 0 4.2193222 0 0 4.4851546 0 0 4.7509875 0 0 5.01682 0 0 5.2826524 0 0 5.5484853 
		0 0 5.8143172 0 0 6.0801501 0 0 6.345983 0 0 6.611815 0 0 6.8776479 0 0 7.1434803 
		0 0 7.4093127 0 0 0.57222253 0 0 0.70734996 0 0 0.8424775 0 0 0.97760493 0 0 1.1127325 
		0 0 1.24786 0 0 1.3829874 0 0 1.5181149 0 0 1.6532423 0 0 1.7883698 0 0 1.9234973 
		0 0 2.0586247 0 0 2.1937523 0 0 2.3288798 0 0 2.4640074 0 0 2.5991347 0 0 2.7342622 
		0 0 2.8693898 0 0 3.0045171 0 0 3.1396446 0 0 3.2747722 0 0 3.4098995 0 0 3.545027 
		0 0 3.6801546 0 0 3.8152819 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 
		0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 
		0 0 0 0 0 0 0 0 0 -0.57222408 0 0 -0.70735192 0 0 -0.84247983 0 0 -0.97760767 0 0 
		-1.1127356 0 0 -1.2478634 0 0 -1.3829913 0 0 -1.5181192 0 0 -1.653247 0 0 -1.7883749 
		0 0 -1.9235028 0 0 -2.0586307 0 0 -2.1937585 0 0 -2.3288865 0 0 -2.4640143 0 0 -2.5991421 
		0 0 -2.7342701 0 0 -2.8693979 0 0 -3.0045257 0 0 -3.1396537 0 0 -3.2747815 0 0 -3.4099092 
		0 0 -3.5450373 0 0 -3.6801651 0 0 -3.8152928 0 0 -1.0293322 0 0 -1.2951648 0 0 -1.5609976 
		0 0 -1.8268303 0 0 -2.0926633 0 0 -2.358496 0 0 -2.6243286 0 0 -2.8901613 0 0 -3.1559942 
		0 0 -3.4218268 0 0 -3.6876595 0 0 -3.9534922 0 0 -4.2193251 0 0 -4.485158 0;
	setAttr ".pt[664:829]" 0 -4.7509909 0 0 -5.0168233 0 0 -5.2826562 0 0 -5.5484891 
		0 0 -5.8143215 0 0 -6.0801544 0 0 -6.3459868 0 0 -6.6118197 0 0 -6.8776522 0 0 -7.1434851 
		0 0 -7.409318 0 0 -1.2673689 0 0 -1.655206 0 0 -2.0430434 0 0 -2.4308803 0 0 -2.8187177 
		0 0 -3.2065549 0 0 -3.5943918 0 0 -3.9822292 0 0 -4.3700662 0 0 -4.7579036 0 0 -5.1457405 
		0 0 -5.5335779 0 0 -5.9214149 0 0 -6.3092523 0 0 -6.6970897 0 0 -7.0849261 0 0 -7.4727635 
		0 0 -7.8606009 0 0 -8.2484379 0 0 -8.6362753 0 0 -9.0241127 0 0 -9.4119492 0 0 -9.7997866 
		0 0 -10.187624 0 0 -10.57546 0 0 -1.2037593 0 0 -1.7009076 0 0 -2.1980562 0 0 -2.6952043 
		0 0 -3.192353 0 0 -3.6895013 0 0 -4.1866493 0 0 -4.6837978 0 0 -5.1809464 0 0 -5.6780944 
		0 0 -6.1752429 0 0 -6.6723914 0 0 -7.1695395 0 0 -7.666688 0 0 -8.1638365 0 0 -8.660985 
		0 0 -9.1581335 0 0 -9.655282 0 0 -10.15243 0 0 -10.649578 0 0 -11.146727 0 0 -11.643875 
		0 0 -12.141024 0 0 -12.638172 0 0 -13.13532 0 0 -0.78574735 0 0 -1.3759352 0 0 -1.9661236 
		0 0 -2.5563114 0 0 -3.1464999 0 0 -3.7366877 0 0 -4.3268757 0 0 -4.9170637 0 0 -5.5072517 
		0 0 -6.0974398 0 0 -6.6876278 0 0 -7.2778158 0 0 -7.8680038 0 0 -8.4581919 0 0 -9.0483799 
		0 0 -9.6385679 0 0 -10.228756 0 0 -10.818944 0 0 -11.409132 0 0 -11.99932 0 0 -12.589508 
		0 0 -13.179696 0 0 -13.769884 0 0 -14.360073 0 0 -14.95026 0 0 0.0036735535 0 0 -0.66023773 
		0 0 -1.3241495 0 0 -1.9880607 0 0 -2.6519725 0 0 -3.3158839 0 0 -3.979795 0 0 -4.6437068 
		0 0 -5.3076181 0 0 -5.9715295 0 0 -6.6354413 0 0 -7.2993522 0 0 -7.9632635 0 0 -8.6271753 
		0 0 -9.2910872 0 0 -9.954998 0 0 -10.61891 0 0 -11.282822 0 0 -11.946733 0 0 -12.610644 
		0 0 -13.274556 0 0 -13.938467 0 0 -14.602378 0 0 -15.26629 0 0 -15.930201 0 0 1.1428556 
		0 0 0.42695004 0 0 -0.28895611 0 0 -1.0048617 0 0 -1.7207679 0 0 -2.4366734 0 0 -3.1525791 
		0 0 -3.8684852 0 0 -4.5843906 0 0 -5.3002963 0 0 -6.0162024 0 0 -6.7321081 0 0 -7.4480138 
		0 0 -8.1639204 0 0 -8.8798265 0 0 -9.5957308 0 0 -10.311637 0 0 -11.027543 0 0 -11.743448 
		0 0 -12.459354 0 0 -13.175261 0 0 -13.891166 0 0 -14.607072 0 0 -15.322978 0 0 -16.038883 
		0 0 2.5718699 0 0 1.8274008 0 0 1.0829314 0 0 0.33846253 0 0 -0.40600693 0 0 -1.1504759 
		0 0 -1.8949447 0 0 -2.6394141 0 0 -3.383883 0 0 -4.1283517 0 0 -4.8728213 0 0 -5.61729 
		0 0 -6.3617592 0 0 -7.1062284 0 0 -7.850698 0 0 -8.5951662 0 0 -9.3396358 0 0 -10.084105 
		0 0 -10.828573 0 0 -11.573043 0 0 -12.317513 0 0 -13.061981 0 0 -13.80645 0 0 -14.55092 
		0 0 -15.295388 0 0 4.1962223 0 0 3.4475558 0 0 2.6988888 0 0 1.9502224 0 0 1.2015554 
		0;
	setAttr ".pt[830:995]" 0 0.45288897 0 0 -0.29577747 0 0 -1.0444444 0 0 -1.7931108 
		0 0 -2.5417774 0 0 -3.2904444 0 0 -4.0391107 0 0 -4.7877769 0 0 -5.5364442 0 0 -6.285111 
		0 0 -7.0337772 0 0 -7.782444 0 0 -8.5311108 0 0 -9.2797766 0 0 -10.028444 0 0 -10.777111 
		0 0 -11.525777 0 0 -12.274444 0 0 -13.02311 0 0 -13.771776 0 0 5.8935995 0 0 5.1652389 
		0 0 4.4368773 0 0 3.7085166 0 0 2.9801552 0 0 2.2517946 0 0 1.5234338 0 0 0.7950725 
		0 0 0.066711716 0 0 -0.66164905 0 0 -1.3900104 0 0 -2.118371 0 0 -2.8467319 0 0 -3.5750933 
		0 0 -4.3034544 0 0 -5.0318146 0 0 -5.7601762 0 0 -6.4885373 0 0 -7.2168975 0 0 -7.9452586 
		0 0 -8.6736202 0 0 -9.4019804 0 0 -10.130342 0 0 -10.858703 0 0 -11.587063 0 0 7.5231552 
		0 0 6.8389387 0 0 6.1547217 0 0 5.4705052 0 0 4.7862878 0 0 4.1020713 0 0 3.4178548 
		0 0 2.7336378 0 0 2.0494211 0 0 1.3652045 0 0 0.68098742 0 0 -0.0032291724 0 0 -0.68744576 
		0 0 -1.3716629 0 0 -2.0558798 0 0 -2.7400961 0 0 -3.4243131 0 0 -4.10853 0 0 -4.7927465 
		0 0 -5.4769635 0 0 -6.1611805 0 0 -6.8453965 0 0 -7.5296135 0 0 -8.2138309 0 0 -8.8980465 
		0 0 8.9366894 0 0 8.3190107 0 0 7.7013321 0 0 7.083653 0 0 6.4659739 0 0 5.8482952 
		0 0 5.2306166 0 0 4.6129375 0 0 3.9952588 0 0 3.3775802 0 0 2.759901 0 0 2.1422224 
		0 0 1.5245438 0 0 0.90686458 0 0 0.28918543 0 0 -0.32849279 0 0 -0.94617194 0 0 -1.5638511 
		0 0 -2.1815293 0 0 -2.7992084 0 0 -3.4168875 0 0 -4.0345659 0 0 -4.652245 0 0 -5.2699242 
		0 0 -5.8876023 0 0 9.9907541 0 0 9.4598303 0 0 8.9289055 0 0 8.3979807 0 0 7.8670559 
		0 0 7.3361311 0 0 6.8052068 0 0 6.274282 0 0 5.7433572 0 0 5.2124329 0 0 4.6815081 
		0 0 4.1505837 0 0 3.6196592 0 0 3.0887341 0 0 2.5578094 0 0 2.0268853 0 0 1.4959605 
		0 0 0.96503556 0 0 0.43411145 0 0 -0.096813411 0 0 -0.6277383 0 0 -1.1586623 0 0 
		-1.6895872 0 0 -2.2205122 0 0 -2.7514362 0 0 10.558793 0 0 10.131999 0 0 9.705205 
		0 0 9.2784109 0 0 8.8516169 0 0 8.4248228 0 0 7.9980292 0 0 7.5712347 0 0 7.1444411 
		0 0 6.7176471 0 0 6.290853 0 0 5.864059 0 0 5.4372654 0 0 5.0104709 0 0 4.5836768 
		0 0 4.1568832 0 0 3.7300892 0 0 3.3032949 0 0 2.8765013 0 0 2.4497073 0 0 2.022913 
		0 0 1.5961195 0 0 1.1693254 0 0 0.74253112 0 0 0.31573761 0 0 10.542358 0 0 10.233664 
		0 0 9.9249687 0 0 9.6162739 0 0 9.307579 0 0 8.9988842 0 0 8.6901894 0 0 8.3814945 
		0 0 8.0727997 0 0 7.7641053 0 0 7.4554105 0 0 7.1467156 0 0 6.8380208 0 0 6.529326 
		0 0 6.2206311 0 0 5.9119363 0 0 5.6032414 0 0 5.2945466 0 0 4.9858522 0 0 4.6771574 
		0 0 4.3684621 0;
	setAttr ".pt[996:1161]" 0 4.0597677 0 0 3.7510729 0 0 3.4423778 0 0 3.1336834 
		0 0 9.8804417 0 0 9.6999493 0 0 9.5194578 0 0 9.3389654 0 0 9.158474 0 0 8.9779816 
		0 0 8.7974901 0 0 8.6169977 0 0 8.4365063 0 0 8.2560139 0 0 8.0755215 0 0 7.89503 
		0 0 7.7145381 0 0 7.5340462 0 0 7.3535542 0 0 7.1730623 0 0 6.9925704 0 0 6.812078 
		0 0 6.6315866 0 0 6.4510946 0 0 6.2706022 0 0 6.0901108 0 0 5.9096184 0 0 5.7291265 
		0 0 5.548635 0 0 8.5561991 0 0 8.5098171 0 0 8.4634342 0 0 8.4170523 0 0 8.3706703 
		0 0 8.3242884 0 0 8.2779064 0 0 8.2315235 0 0 8.1851416 0 0 8.1387596 0 0 8.0923777 
		0 0 8.0459957 0 0 7.9996133 0 0 7.9532309 0 0 7.9068489 0 0 7.860467 0 0 7.8140845 
		0 0 7.7677026 0 0 7.7213206 0 0 7.6749382 0 0 7.6285563 0 0 7.5821738 0 0 7.5357919 
		0 0 7.4894099 0 0 7.4430275 0 0 6.6004457 0 0 6.6896911 0 0 6.7789369 0 0 6.8681827 
		0 0 6.9574285 0 0 7.0466743 0 0 7.13592 0 0 7.2251658 0 0 7.3144112 0 0 7.403657 
		0 0 7.4929028 0 0 7.5821486 0 0 7.6713943 0 0 7.7606401 0 0 7.8498859 0 0 7.9391313 
		0 0 8.0283775 0 0 8.1176233 0 0 8.2068682 0 0 8.296114 0 0 8.3853598 0 0 8.4746056 
		0 0 8.5638514 0 0 8.6530972 0 0 8.7423429 0 0 4.0916042 0 0 4.3135571 0 0 4.5355105 
		0 0 4.7574635 0 0 4.9794164 0 0 5.2013698 0 0 5.4233227 0 0 5.6452756 0 0 5.8672285 
		0 0 6.0891814 0 0 6.3111348 0 0 6.5330877 0 0 6.7550406 0 0 6.9769936 0 0 7.198947 
		0 0 7.4208999 0 0 7.6428528 0 0 7.8648062 0 0 8.0867586 0 0 8.308712 0 0 8.5306654 
		0 0 8.7526178 0 0 8.9745712 0 0 9.1965237 0 0 9.4184771 0 0 1.152063 0 0 1.4994586 
		0 0 1.8468543 0 0 2.1942499 0 0 2.5416458 0 0 2.8890412 0 0 3.2364368 0 0 3.5838325 
		0 0 3.9312282 0 0 4.2786236 0 0 4.6260195 0 0 4.9734149 0 0 5.3208103 0 0 5.6682062 
		0 0 6.0156021 0 0 6.3629975 0 0 6.710393 0 0 7.0577888 0 0 7.4051843 0 0 7.7525802 
		0 0 8.0999756 0 0 8.4473715 0 0 8.7947674 0 0 9.1421623 0 0 9.4895582 0 0 -2.0589619 
		0 0 -1.5974936 0 0 -1.1360251 0 0 -0.67455691 0 0 -0.21308838 0 0 0.24837983 0 0 
		0.70984805 0 0 1.1713166 0 0 1.6327847 0 0 2.0942531 0 0 2.5557215 0 0 3.0171897 
		0 0 3.478658 0 0 3.9401264 0 0 4.4015951 0 0 4.8630629 0 0 5.3245316 0 0 5.7859998 
		0 0 6.247468 0 0 6.7089362 0 0 7.1704049 0 0 7.6318727 0 0 8.0933409 0 0 8.5548096 
		0 0 9.0162773 0 0 -5.3554482 0 0 -4.7950106 0 0 -4.2345724 0 0 -3.6741347 0 0 -3.1136966 
		0 0 -2.5532589 0 0 -1.9928212 0 0 -1.4323831 0 0 -0.87194538 0 0 -0.31150764 0 0 
		0.2489305 0 0 0.80936825 0;
	setAttr ".pt[1162:1224]" 0 1.3698059 0 0 1.9302441 0 0 2.4906821 0 0 3.0511196 
		0 0 3.6115577 0 0 4.1719956 0 0 4.7324333 0 0 5.2928715 0 0 5.8533096 0 0 6.4137468 
		0 0 6.974185 0 0 7.5346231 0 0 8.0950603 0 0 -8.5368309 0 0 -7.8957667 0 0 -7.2547021 
		0 0 -6.6136374 0 0 -5.9725728 0 0 -5.3315086 0 0 -4.690444 0 0 -4.0493793 0 0 -3.4083149 
		0 0 -2.7672505 0 0 -2.1261857 0 0 -1.4851214 0 0 -0.84405696 0 0 -0.20299211 0 0 
		0.43807271 0 0 1.0791366 0 0 1.7202015 0 0 2.3612664 0 0 3.0023303 0 0 3.6433949 
		0 0 4.2844601 0 0 4.9255238 0 0 5.5665884 0 0 6.2076535 0 0 6.8487172 0 0 -11.401727 
		0 0 -10.701017 0 0 -10.000307 0 0 -9.2995977 0 0 -8.5988874 0 0 -7.8981781 0 0 -7.1974683 
		0 0 -6.4967585 0 0 -5.7960486 0 0 -5.0953393 0 0 -4.394629 0 0 -3.6939194 0 0 -2.9932098 
		0 0 -2.2924998 0 0 -1.5917896 0 0 -0.8910805 0 0 -0.19037041 0 0 0.51033968 0 0 1.2110488 
		0 0 1.9117589 0 0 2.612469 0 0 3.3131781 0 0 4.0138884 0 0 4.7145982 0 0 5.4153075 
		0;
	setAttr ".ndt" 0;
createNode lightLinker -s -n "lightLinker1";
	rename -uid "2644875F-41B3-3F25-02E5-6EB59BEEA541";
	setAttr -s 2 ".lnk";
	setAttr -s 2 ".slnk";
createNode displayLayerManager -n "layerManager";
	rename -uid "7BDDAC6E-4711-F926-E115-579017EE5203";
createNode displayLayer -n "defaultLayer";
	rename -uid "6DA5D8B9-460F-DE1E-B3C3-7E92DA0E608D";
	setAttr ".ufem" -type "stringArray" 0  ;
createNode renderLayerManager -n "renderLayerManager";
	rename -uid "D91BC5C6-457C-912B-300D-E6BB1526D343";
createNode renderLayer -n "defaultRenderLayer";
	rename -uid "4ED6C842-44A4-18E7-0588-E0AB74541890";
	setAttr ".g" yes;
createNode script -n "uiConfigurationScriptNode";
	rename -uid "CD4D286A-4E80-131A-BCB2-2CAE42AA9149";
	setAttr ".b" -type "string" "// Maya Mel UI Configuration File.\n// No UI generated in batch mode.\n";
	setAttr ".st" 3;
createNode script -n "sceneConfigurationScriptNode";
	rename -uid "A483DF2B-437F-C955-F575-D89C3A561D4D";
	setAttr ".b" -type "string" "playbackOptions -min 1 -max 80 -ast 1 -aet 200 ";
	setAttr ".st" 6;
createNode polyCylinder -n "polyCylinder1";
	rename -uid "EDC82E5E-47B9-7FBF-7AD9-E1854F9DAEF2";
	setAttr ".ax" -type "double3" 1 0 0 ;
	setAttr ".r" 34;
	setAttr ".h" 22.1;
	setAttr ".sa" 24;
	setAttr ".sc" 1;
createNode polyCylinder -n "polyCylinder2";
	rename -uid "0A5039D1-4626-8219-6933-5E9055E586E8";
	setAttr ".ax" -type "double3" 1 0 0 ;
	setAttr ".r" 34;
	setAttr ".h" 22.1;
	setAttr ".sa" 24;
	setAttr ".sc" 1;
createNode polyCylinder -n "polyCylinder3";
	rename -uid "9876FC3C-42B9-D74E-EB23-E1BC904AA8E4";
	setAttr ".ax" -type "double3" 1 0 0 ;
	setAttr ".r" 34;
	setAttr ".h" 22.1;
	setAttr ".sa" 24;
	setAttr ".sc" 1;
createNode polyCylinder -n "polyCylinder4";
	rename -uid "A6AFE383-4E3A-F609-FC76-349BAC2C0BD0";
	setAttr ".ax" -type "double3" 1 0 0 ;
	setAttr ".r" 34;
	setAttr ".h" 22.1;
	setAttr ".sa" 24;
	setAttr ".sc" 1;
createNode polyCube -n "polyCube1";
	rename -uid "9BC85D34-45BD-B42D-06F9-12924FBB24DA";
	setAttr ".w" 176;
	setAttr ".h" 50;
	setAttr ".d" 300;
createNode polyPlane -n "polyPlane1";
	rename -uid "5597D979-4DFD-07B8-2158-CE9C44E01F71";
	setAttr ".w" 1000;
	setAttr ".h" 1000;
	setAttr ".sw" 24;
	setAttr ".sh" 48;
createNode animCurveTL -n "vehicle_global_CTRL_translateX";
	rename -uid "8D51037D-4170-B0D8-0ECE-04A929701210";
	setAttr ".tan" 18;
	setAttr ".wgt" no;
	setAttr -s 3 ".ktv[0:2]"  1 0 40 60 80 0;
createNode animCurveTL -n "vehicle_global_CTRL_translateZ";
	rename -uid "A3634A21-4626-FAA0-E713-508EB473F0D9";
	setAttr ".tan" 18;
	setAttr ".wgt" no;
	setAttr -s 3 ".ktv[0:2]"  1 -300 40 0 80 300;
createNode animCurveTA -n "vehicle_global_CTRL_rotateY";
	rename -uid "77746E1B-4BD7-DB07-DAFD-5892FE448AB0";
	setAttr ".tan" 18;
	setAttr ".wgt" no;
	setAttr -s 3 ".ktv[0:2]"  1 0 40 12.000000000000002 80 0;
createNode animCurveTU -n "vehicle_chassis_CTRL_steering";
	rename -uid "B863B06C-4A7E-019C-15DA-3D988DD77684";
	setAttr ".tan" 18;
	setAttr ".wgt" no;
	setAttr -s 3 ".ktv[0:2]"  1 0 40 0 80 0;
createNode animCurveTL -n "front_left_suspension_DRV_translateX";
	rename -uid "E5AE665F-4C22-1785-7D44-718323AA4753";
	setAttr ".tan" 18;
	setAttr ".wgt" no;
	setAttr -s 80 ".ktv[0:79]"  1 -80 2 -80 3 -80 4 -80 5 -80 6 -80 7 -80
		 8 -80 9 -80 10 -80 11 -80 12 -80 13 -80 14 -80 15 -80 16 -80 17 -80 18 -80 19 -80
		 20 -80 21 -80 22 -80 23 -80 24 -80 25 -80 26 -80 27 -80 28 -80 29 -80 30 -80 31 -80
		 32 -80 33 -80 34 -80 35 -80 36 -80 37 -80 38 -80 39 -80 40 -80 41 -80 42 -80 43 -80
		 44 -80 45 -80 46 -80 47 -80 48 -80 49 -80 50 -80 51 -80 52 -80 53 -80 54 -80 55 -80
		 56 -80 57 -80 58 -80 59 -80 60 -80 61 -80 62 -80 63 -80 64 -80 65 -80 66 -80 67 -80
		 68 -80 69 -80 70 -80 71 -80 72 -80 73 -80 74 -80 75 -80 76 -80 77 -80 78 -80 79 -80
		 80 -80;
createNode animCurveTL -n "front_left_suspension_DRV_translateY";
	rename -uid "9593C069-4DA2-E0DC-51BD-1FBC32C81CDC";
	setAttr ".tan" 18;
	setAttr ".wgt" no;
	setAttr -s 80 ".ktv[0:79]"  1 30.183120587496028 2 30.153358319429621
		 3 30.065627911714778 4 29.922256329683528 5 29.725585797456965 6 29.477950909761653
		 7 29.181983807710871 8 28.88334582918668 9 28.604045139489415 10 28.29466174715543
		 11 27.933818883319908 12 27.739555425067955 13 27.528602666278893 14 27.316172188486817
		 15 27.299276894297364 16 27.278532570566895 17 27.406140112848199 18 27.625424170465386
		 19 27.944676568731545 20 28.41058843396592 21 28.938678371387724 22 29.633704769092802
		 23 30.331237422901395 24 31.224833467858865 25 32.086157778161599 26 33.05502518600133
		 27 34.001737679897815 28 34.958795680858564 29 35.901746883251143 30 36.763224675626724
		 31 37.614207341642349 32 38.317626582064115 33 39.000911341585599 34 39.517884444470511
		 35 39.980096053357229 36 40.320687133645087 37 40.537636596535712 38 40.746907073830634
		 39 40.724455421648123 40 40.704939430437186 41 40.628730784304693 42 40.387649546511724
		 43 40.137355814822271 44 39.737132165167893 45 39.245528313849533 46 38.695373452737861
		 47 37.982700265482002 48 37.260802682428199 49 36.376197274713356 50 35.49605985336342
		 51 34.510982949066545 52 33.522149276346042 53 32.520558547586276 54 31.522912215799167
		 55 30.567493465014209 56 29.652195003100147 57 28.817171271170011 58 28.064920599783292
		 59 27.409931983079915 60 26.882160986986165 61 26.437263333754743 62 26.168361508803571
		 63 25.927205385217157 64 25.920312227258172 65 25.913667024621454 66 26.069766997971769
		 67 26.286422729172941 68 26.492019653001066 69 26.882722299139914 70 27.239701669257101
		 71 27.57016507868093 72 27.982237602536067 73 28.371073509518489 74 28.715353752438411
		 75 29.012827659909114 76 29.261252189938411 77 29.515996398535897 78 29.683850707617928
		 79 29.791718902198006 80 29.828290404883553;
createNode animCurveTL -n "front_left_suspension_DRV_translateZ";
	rename -uid "6DA640C0-4CDD-33E0-E953-C1AAA880BC7F";
	setAttr ".tan" 18;
	setAttr ".wgt" no;
	setAttr -s 80 ".ktv[0:79]"  1 -180 2 -179.60814740981021 3 -178.4530753162316
		 4 -176.56551223475043 5 -173.97618668085283 6 -170.71582717002514 7 -166.81516221775348
		 8 -162.30492033952407 9 -157.21583005082317 10 -151.57861986713698 11 -145.42401830395164
		 12 -138.78275387675347 13 -131.68555510102863 14 -124.16315049226327 15 -116.24626856594372
		 16 -107.96563783755616 17 -99.351986822586753 18 -90.436044036521764 19 -81.248537994847396
		 20 -71.820197213049795 21 -62.181750206615277 22 -52.363925491030017 23 -42.397451581780217
		 24 -32.31305699435211 25 -22.141470244231868 26 -11.913419846905782 27 -1.6596343178599113
		 28 8.5891578274193989 29 18.802228073445917 30 28.948847904733526 31 38.998288805795909
		 32 48.919822261146948 33 58.682719755300411 34 68.256252772770125 35 77.609692798069659
		 36 86.712311315713066 37 95.533379810214058 38 104.04216976608632 39 112.2079526678437
		 40 120 41 127.77306170886035 42 135.88386075949296 43 144.30462816455596 44 153.00759493670756
		 45 161.9649920886061 46 171.14905063290968 47 180.53200158227659 48 190.08607594936507
		 49 199.78350474683327 50 209.59651898733958 51 219.49734968354201 52 229.45822784809891
		 53 239.45138449366857 54 249.44905063290906 55 259.42345727847862 56 269.34683544303573
		 57 279.1914161392383 58 288.92943037974464 59 298.53310917721313 60 307.9746835443018
		 61 317.226384493669 62 326.26044303797295 63 335.04909018987178 64 343.56455696202374
		 65 351.77907436708722 66 359.66487341772029 67 367.19418512658109 68 374.33924050632811
		 69 381.07227056961938 70 387.36550632911315 71 393.19117879746773 72 398.52151898734121
		 73 403.32875791139196 74 407.58512658227818 75 411.26285601265801 76 414.3341772151897
		 77 416.77132120253151 78 418.5465189873417 79 419.63200158227846 80 420;
createNode animCurveTA -n "front_left_suspension_DRV_rotateX";
	rename -uid "2E579CBC-45F2-9DA5-7BC4-299B2D5021A5";
	setAttr ".tan" 18;
	setAttr ".wgt" no;
	setAttr -s 80 ".ktv[0:79]"  1 4.3370812176945295 2 4.3370812176945295
		 3 4.3370812176945295 4 4.3370812176945295 5 4.3370812176945295 6 4.3370812176945295
		 7 4.3370812176945295 8 3.1017387346666005 9 3.1017387346666005 10 3.1017387346666005
		 11 1.6308654149057837 12 1.6308654149057837 13 1.6308654149057837 14 0.042142581832250996
		 15 0.042142581832250996 16 0.042142581832250996 17 -1.5366003866972884 18 -1.5366003866972884
		 19 -2.9787883838179492 20 -2.9787883838179492 21 -4.1702753664443728 22 -4.1702753664443728
		 23 -4.1702753664443728 24 -5.0185837569463549 25 -5.0185837569463549 26 -5.4592272974708029
		 27 -5.4592272974708029 28 -5.4592281474264537 29 -5.4592281474264537 30 -5.0185855846099754
		 31 -5.0185855846099754 32 -4.1702753665661243 33 -4.1702753665661243 34 -2.978789094762063
		 35 -2.978789094762063 36 -1.5366042125012245 37 -1.5366042125012245 38 -1.5366042125012245
		 39 0.042140508295318513 40 0.042140508295318513 41 1.630862205154378 42 1.630862205154378
		 43 1.630862205154378 44 3.1017350844892717 45 3.1017350844892717 46 4.3370818982554429
		 47 4.3370818982554429 48 5.2390043644940691 49 5.2390043644940691 50 5.7362902647793996
		 51 5.7362902647793996 52 5.788442204707918 53 5.788442204707918 54 5.788442204707918
		 55 5.3876354626209064 56 5.3876354626209064 57 4.559263909000391 58 4.559263909000391
		 59 3.361171959154361 60 3.361171959154361 61 1.8810110020657291 62 1.8810110020657291
		 63 0.23077470312399456 64 0.23077470312399456 65 0.23077470312399456 66 -1.4618559282431067
		 67 -1.4618559282431067 68 -1.4618559282431067 69 -3.064655229470667 70 -3.064655229470667
		 71 -3.064655229470667 72 -4.4528145556317718 73 -4.4528145556317718 74 -4.4528145556317718
		 75 -4.4528145556317718 76 -4.4528145556317718 77 -5.5194735326908901 78 -5.5194735326908901
		 79 -5.5194735326908901 80 -5.5194735326908901;
createNode animCurveTA -n "front_left_suspension_DRV_rotateY";
	rename -uid "73B93733-4867-66A7-52DE-C69283275025";
	setAttr ".tan" 18;
	setAttr ".wgt" no;
	setAttr -s 80 ".ktv[0:79]"  1 -6.2120208622334296e-18 2 -6.2120208622334296e-18
		 3 -6.2120208622334296e-18 4 -6.2120208622334296e-18 5 -6.2120208622334296e-18 6 -6.2120208622334296e-18
		 7 -6.2120208622334296e-18 8 -3.1060104311167171e-18 9 -3.1060104311167171e-18 10 -3.1060104311167171e-18
		 11 0 12 0 13 0 14 0 15 0 16 0 17 0 18 0 19 0 20 0 21 -3.1060104311167152e-18 22 -3.1060104311167152e-18
		 23 -3.1060104311167152e-18 24 0 25 0 26 7.765026077791789e-19 27 7.765026077791789e-19
		 28 0 29 0 30 0 31 0 32 0 33 0 34 0 35 0 36 -1.5530052155583582e-18 37 -1.5530052155583582e-18
		 38 -1.5530052155583582e-18 39 0 40 0 41 0 42 0 43 0 44 -3.1060104311167164e-18 45 -3.1060104311167164e-18
		 46 0 47 0 48 -6.2120208622334327e-18 49 -6.2120208622334327e-18 50 6.2120208622334343e-18
		 51 6.2120208622334343e-18 52 -6.2120208622334312e-18 53 -6.2120208622334312e-18 54 -6.2120208622334312e-18
		 55 0 56 0 57 -3.1060104311167164e-18 58 -3.1060104311167164e-18 59 0 60 0 61 -7.765026077791789e-19
		 62 -7.765026077791789e-19 63 -4.8531412986198675e-20 64 -4.8531412986198675e-20 65 -4.8531412986198675e-20
		 66 -4.8531412986198681e-20 67 -4.8531412986198681e-20 68 -4.8531412986198681e-20
		 69 7.765026077791789e-19 70 7.765026077791789e-19 71 7.765026077791789e-19 72 0 73 0
		 74 0 75 0 76 0 77 0 78 0 79 0 80 0;
createNode animCurveTA -n "front_left_suspension_DRV_rotateZ";
	rename -uid "DED44DC8-4552-9097-7995-94A87A82F0DA";
	setAttr ".tan" 18;
	setAttr ".wgt" no;
	setAttr -s 80 ".ktv[0:79]"  1 -1.0264918764802351 2 -1.0264918764802351
		 3 -1.0264918764802351 4 -1.0264918764802351 5 -1.0264918764802351 6 -1.0264918764802351
		 7 -1.0264918764802351 8 -1.0039779736305723 9 -1.0039779736305723 10 -1.0039779736305723
		 11 -0.94860534602709645 12 -0.94860534602709645 13 -0.94860534602709645 14 -0.8621900483567797
		 15 -0.8621900483567797 16 -0.8621900483567797 17 -0.74755510585220786 18 -0.74755510585220786
		 19 -0.60844871207721096 20 -0.60844871207721096 21 -0.44942151071289721 22 -0.44942151071289721
		 23 -0.44942151071289721 24 -0.27567821815861537 25 -0.27567821815861537 26 -0.092907042925807246
		 27 -0.092907042925807246 28 0.092906687799799839 29 0.092906687799799839 30 0.27567782670464241
		 31 0.27567782670464241 32 0.44942129670944481 33 0.44942129670944481 34 0.60844847915759748
		 35 0.60844847915759748 36 0.74755424304107088 37 0.74755424304107088 38 0.74755424304107088
		 39 0.86219009581295181 40 0.86219009581295181 41 0.94860518908807134 42 0.94860518908807134
		 43 0.94860518908807134 44 1.0039765374907619 45 1.0039765374907619 46 1.0264943990898625
		 47 1.0264943990898625 48 1.0154227705558907 49 1.0154227705558907 50 0.97112188193723215
		 51 0.97112188193723215 52 0.89504167859292949 53 0.89504167859292949 54 0.89504167859292949
		 55 0.78967121830140163 56 0.78967121830140163 57 0.65845107595305119 58 0.65845107595305119
		 59 0.50567187932333879 60 0.50567187932333879 61 0.33633708279896107 62 0.33633708279896107
		 63 0.15598651434764133 64 0.15598651434764133 65 0.15598651434764133 66 -0.029471281324985402
		 67 -0.029471281324985402 68 -0.029471281324985402 69 -0.21396274049428246 70 -0.21396274049428246
		 71 -0.21396274049428246 72 -0.39144975420884337 73 -0.39144975420884337 74 -0.39144975420884337
		 75 -0.39144975420884337 76 -0.39144975420884337 77 -0.55611988001445156 78 -0.55611988001445156
		 79 -0.55611988001445156 80 -0.55611988001445156;
createNode animCurveTL -n "front_left_steer_DRV_translateX";
	rename -uid "EC41F56E-4C8D-8178-AF97-439DBF4524B1";
	setAttr ".tan" 18;
	setAttr ".wgt" no;
	setAttr -s 80 ".ktv[0:79]"  1 0 2 0 3 0 4 0 5 0 6 0 7 0 8 0 9 0 10 0
		 11 0 12 0 13 0 14 0 15 0 16 0 17 0 18 0 19 0 20 0 21 0 22 0 23 0 24 0 25 0 26 0 27 0
		 28 0 29 0 30 0 31 0 32 0 33 0 34 0 35 0 36 0 37 0 38 0 39 0 40 0 41 0 42 0 43 0 44 0
		 45 0 46 0 47 0 48 0 49 0 50 0 51 0 52 0 53 0 54 0 55 0 56 0 57 0 58 0 59 0 60 0 61 0
		 62 0 63 0 64 0 65 0 66 0 67 0 68 0 69 0 70 0 71 0 72 0 73 0 74 0 75 0 76 0 77 0 78 0
		 79 0 80 0;
createNode animCurveTL -n "front_left_steer_DRV_translateY";
	rename -uid "9BF684A6-42F9-094C-6706-A69E5754A8BA";
	setAttr ".tan" 18;
	setAttr ".wgt" no;
	setAttr -s 80 ".ktv[0:79]"  1 0 2 0 3 0 4 0 5 0 6 0 7 0 8 0 9 0 10 0
		 11 0 12 0 13 0 14 0 15 0 16 0 17 0 18 0 19 0 20 0 21 0 22 0 23 0 24 0 25 0 26 0 27 0
		 28 0 29 0 30 0 31 0 32 0 33 0 34 0 35 0 36 0 37 0 38 0 39 0 40 0 41 0 42 0 43 0 44 0
		 45 0 46 0 47 0 48 0 49 0 50 0 51 0 52 0 53 0 54 0 55 0 56 0 57 0 58 0 59 0 60 0 61 0
		 62 0 63 0 64 0 65 0 66 0 67 0 68 0 69 0 70 0 71 0 72 0 73 0 74 0 75 0 76 0 77 0 78 0
		 79 0 80 0;
createNode animCurveTL -n "front_left_steer_DRV_translateZ";
	rename -uid "0D78D74D-41C1-9774-E134-6E9B32E222FA";
	setAttr ".tan" 18;
	setAttr ".wgt" no;
	setAttr -s 80 ".ktv[0:79]"  1 0 2 0 3 0 4 0 5 0 6 0 7 0 8 0 9 0 10 0
		 11 0 12 0 13 0 14 0 15 0 16 0 17 0 18 0 19 0 20 0 21 0 22 0 23 0 24 0 25 0 26 0 27 0
		 28 0 29 0 30 0 31 0 32 0 33 0 34 0 35 0 36 0 37 0 38 0 39 0 40 0 41 0 42 0 43 0 44 0
		 45 0 46 0 47 0 48 0 49 0 50 0 51 0 52 0 53 0 54 0 55 0 56 0 57 0 58 0 59 0 60 0 61 0
		 62 0 63 0 64 0 65 0 66 0 67 0 68 0 69 0 70 0 71 0 72 0 73 0 74 0 75 0 76 0 77 0 78 0
		 79 0 80 0;
createNode animCurveTA -n "front_left_steer_DRV_rotateX";
	rename -uid "D457CACC-4B00-F4E1-9024-A5857B1C39E7";
	setAttr ".tan" 18;
	setAttr ".wgt" no;
	setAttr -s 80 ".ktv[0:79]"  1 0 2 0 3 0 4 0 5 0 6 0 7 0 8 0 9 0 10 0
		 11 0 12 0 13 0 14 0 15 0 16 0 17 0 18 0 19 0 20 0 21 0 22 0 23 0 24 0 25 0 26 0 27 0
		 28 0 29 0 30 0 31 0 32 0 33 0 34 0 35 0 36 0 37 0 38 0 39 0 40 0 41 0 42 0 43 0 44 0
		 45 0 46 0 47 0 48 0 49 0 50 0 51 0 52 0 53 0 54 0 55 0 56 0 57 0 58 0 59 0 60 0 61 0
		 62 0 63 0 64 0 65 0 66 0 67 0 68 0 69 0 70 0 71 0 72 0 73 0 74 0 75 0 76 0 77 0 78 0
		 79 0 80 0;
createNode animCurveTA -n "front_left_steer_DRV_rotateY";
	rename -uid "0463DB01-4933-7EAA-EC77-A89C0B956236";
	setAttr ".tan" 18;
	setAttr ".wgt" no;
	setAttr -s 80 ".ktv[0:79]"  1 0 2 0 3 0 4 0 5 0 6 0 7 0 8 0 9 0 10 0
		 11 0 12 0 13 0 14 0 15 0 16 0 17 0 18 0 19 0 20 0 21 0 22 0 23 0 24 0 25 0 26 0 27 0
		 28 0 29 0 30 0 31 0 32 0 33 0 34 0 35 0 36 0 37 0 38 0 39 0 40 0 41 0 42 0 43 0 44 0
		 45 0 46 0 47 0 48 0 49 0 50 0 51 0 52 0 53 0 54 0 55 0 56 0 57 0 58 0 59 0 60 0 61 0
		 62 0 63 0 64 0 65 0 66 0 67 0 68 0 69 0 70 0 71 0 72 0 73 0 74 0 75 0 76 0 77 0 78 0
		 79 0 80 0;
createNode animCurveTA -n "front_left_steer_DRV_rotateZ";
	rename -uid "E05AE4AA-4042-8684-2A6D-60A843F5942B";
	setAttr ".tan" 18;
	setAttr ".wgt" no;
	setAttr -s 80 ".ktv[0:79]"  1 0 2 0 3 0 4 0 5 0 6 0 7 0 8 0 9 0 10 0
		 11 0 12 0 13 0 14 0 15 0 16 0 17 0 18 0 19 0 20 0 21 0 22 0 23 0 24 0 25 0 26 0 27 0
		 28 0 29 0 30 0 31 0 32 0 33 0 34 0 35 0 36 0 37 0 38 0 39 0 40 0 41 0 42 0 43 0 44 0
		 45 0 46 0 47 0 48 0 49 0 50 0 51 0 52 0 53 0 54 0 55 0 56 0 57 0 58 0 59 0 60 0 61 0
		 62 0 63 0 64 0 65 0 66 0 67 0 68 0 69 0 70 0 71 0 72 0 73 0 74 0 75 0 76 0 77 0 78 0
		 79 0 80 0;
createNode animCurveTL -n "front_left_spin_DRV_translateX";
	rename -uid "BE30E491-45C7-0C85-3EC4-3ABA11057621";
	setAttr ".tan" 18;
	setAttr ".wgt" no;
	setAttr -s 80 ".ktv[0:79]"  1 0 2 0 3 0 4 0 5 0 6 0 7 0 8 0 9 0 10 0
		 11 0 12 0 13 0 14 0 15 0 16 0 17 0 18 0 19 0 20 0 21 0 22 0 23 0 24 0 25 0 26 0 27 0
		 28 0 29 0 30 0 31 0 32 0 33 0 34 0 35 0 36 0 37 0 38 0 39 0 40 0 41 0 42 0 43 0 44 0
		 45 0 46 0 47 0 48 0 49 0 50 0 51 0 52 0 53 0 54 0 55 0 56 0 57 0 58 0 59 0 60 0 61 0
		 62 0 63 0 64 0 65 0 66 0 67 0 68 0 69 0 70 0 71 0 72 0 73 0 74 0 75 0 76 0 77 0 78 0
		 79 0 80 0;
createNode animCurveTL -n "front_left_spin_DRV_translateY";
	rename -uid "2F713BBE-435B-8580-BD85-00AACC87CD7F";
	setAttr ".tan" 18;
	setAttr ".wgt" no;
	setAttr -s 80 ".ktv[0:79]"  1 0 2 0 3 0 4 0 5 0 6 0 7 0 8 0 9 0 10 0
		 11 0 12 0 13 0 14 0 15 0 16 0 17 0 18 0 19 0 20 0 21 0 22 0 23 0 24 0 25 0 26 0 27 0
		 28 0 29 0 30 0 31 0 32 0 33 0 34 0 35 0 36 0 37 0 38 0 39 0 40 0 41 0 42 0 43 0 44 0
		 45 0 46 0 47 0 48 0 49 0 50 0 51 0 52 0 53 0 54 0 55 0 56 0 57 0 58 0 59 0 60 0 61 0
		 62 0 63 0 64 0 65 0 66 0 67 0 68 0 69 0 70 0 71 0 72 0 73 0 74 0 75 0 76 0 77 0 78 0
		 79 0 80 0;
createNode animCurveTL -n "front_left_spin_DRV_translateZ";
	rename -uid "ED32886E-44B3-A446-8F3E-0CB909410C77";
	setAttr ".tan" 18;
	setAttr ".wgt" no;
	setAttr -s 80 ".ktv[0:79]"  1 0 2 0 3 0 4 0 5 0 6 0 7 0 8 0 9 0 10 0
		 11 0 12 0 13 0 14 0 15 0 16 0 17 0 18 0 19 0 20 0 21 0 22 0 23 0 24 0 25 0 26 0 27 0
		 28 0 29 0 30 0 31 0 32 0 33 0 34 0 35 0 36 0 37 0 38 0 39 0 40 0 41 0 42 0 43 0 44 0
		 45 0 46 0 47 0 48 0 49 0 50 0 51 0 52 0 53 0 54 0 55 0 56 0 57 0 58 0 59 0 60 0 61 0
		 62 0 63 0 64 0 65 0 66 0 67 0 68 0 69 0 70 0 71 0 72 0 73 0 74 0 75 0 76 0 77 0 78 0
		 79 0 80 0;
createNode animCurveTA -n "front_left_spin_DRV_rotateX";
	rename -uid "32FC4DAC-4D9E-3BD9-447C-60B465AA474B";
	setAttr ".tan" 18;
	setAttr ".wgt" no;
	setAttr -s 80 ".ktv[0:79]"  1 0 2 0.6622395564893454 3 2.6143369202996229
		 4 5.8043611050735944 5 10.180379180194937 6 15.690459187176677 7 22.282631254476243
		 8 29.899787749727846 9 38.488669972264027 10 48.002616844460654 11 58.39042548257197
		 12 69.586867168497079 13 81.552124818404124 14 94.232529831871773 15 107.57383896458846
		 16 121.52813126535044 17 136.04516717585906 18 151.07455171581304 19 166.56623529257084
		 20 182.47392302314583 21 198.74022723570249 22 215.3262966983105 23 232.16250920792552
		 24 249.22244143192245 25 266.42455470952086 26 283.73763672817518 27 301.09041100970552
		 28 318.43646758183411 29 335.720337884537 30 352.88024476303593 31 369.87578610608034
		 32 386.63648093537529 33 403.1287949081335 34 419.28475288659502 35 435.06606663335197
		 36 450.41622783021933 37 465.28568506377394 38 479.62874214017546 39 493.38781079307017
		 40 506.51875571854606 41 519.61816464229435 42 533.29226392238877 43 547.48894275307669
		 44 562.17025763645631 45 577.28770017091597 46 592.79193352870141 47 608.64933005833666
		 48 624.79491111165487 49 641.20455478351596 50 657.80717901357366 51 674.57410840842726
		 52 691.44234497302875 53 708.36685427162331 54 725.29825378217868 55 742.18370708662997
		 56 758.97722062919945 57 775.62653393942742 58 792.08557627783637 59 808.30699078052328
		 60 824.24242127071204 61 839.85108367480586 62 855.08167831772414 63 869.89701655526721
		 64 884.24695596076072 65 898.08974695639199 66 911.38071795714586 67 924.07407271559339
		 68 936.11962556483775 69 947.48307557192675 70 958.10524195554615 71 967.9382226600726
		 72 976.94695166698102 73 985.07438590657239 74 992.27048290095138 75 998.48829397709721
		 76 1003.6808714601455 77 1007.8096415219802 78 1010.8144872403171 79 1012.6527120108329
		 80 1013.2759041282137;
createNode animCurveTA -n "front_left_spin_DRV_rotateY";
	rename -uid "44731FE5-48F1-0ABC-723E-698CAAAF5A45";
	setAttr ".tan" 18;
	setAttr ".wgt" no;
	setAttr -s 80 ".ktv[0:79]"  1 0 2 0 3 0 4 0 5 0 6 0 7 0 8 0 9 0 10 0
		 11 0 12 0 13 0 14 0 15 0 16 0 17 0 18 0 19 0 20 0 21 0 22 0 23 0 24 0 25 0 26 0 27 0
		 28 0 29 0 30 0 31 0 32 0 33 0 34 0 35 0 36 0 37 0 38 0 39 0 40 0 41 0 42 0 43 0 44 0
		 45 0 46 0 47 0 48 0 49 0 50 0 51 0 52 0 53 0 54 0 55 0 56 0 57 0 58 0 59 0 60 0 61 0
		 62 0 63 0 64 0 65 0 66 0 67 0 68 0 69 0 70 0 71 0 72 0 73 0 74 0 75 0 76 0 77 0 78 0
		 79 0 80 0;
createNode animCurveTA -n "front_left_spin_DRV_rotateZ";
	rename -uid "29B68413-470D-3FB3-7E45-808E08EC3759";
	setAttr ".tan" 18;
	setAttr ".wgt" no;
	setAttr -s 80 ".ktv[0:79]"  1 0 2 0 3 0 4 0 5 0 6 0 7 0 8 0 9 0 10 0
		 11 0 12 0 13 0 14 0 15 0 16 0 17 0 18 0 19 0 20 0 21 0 22 0 23 0 24 0 25 0 26 0 27 0
		 28 0 29 0 30 0 31 0 32 0 33 0 34 0 35 0 36 0 37 0 38 0 39 0 40 0 41 0 42 0 43 0 44 0
		 45 0 46 0 47 0 48 0 49 0 50 0 51 0 52 0 53 0 54 0 55 0 56 0 57 0 58 0 59 0 60 0 61 0
		 62 0 63 0 64 0 65 0 66 0 67 0 68 0 69 0 70 0 71 0 72 0 73 0 74 0 75 0 76 0 77 0 78 0
		 79 0 80 0;
createNode animCurveTL -n "front_right_suspension_DRV_translateX";
	rename -uid "A426C1DB-425D-B4BB-43BF-749B20AB0034";
	setAttr ".tan" 18;
	setAttr ".wgt" no;
	setAttr -s 80 ".ktv[0:79]"  1 80 2 80 3 80 4 80 5 80 6 80 7 80 8 80
		 9 80 10 80 11 80 12 80 13 80 14 80 15 80 16 80 17 80 18 80 19 80 20 80 21 80 22 80
		 23 80 24 80 25 80 26 80 27 80 28 80 29 80 30 80 31 80 32 80 33 80 34 80 35 80 36 80
		 37 80 38 80 39 80 40 80 41 80 42 80 43 80 44 80 45 80 46 80 47 80 48 80 49 80 50 80
		 51 80 52 80 53 80 54 80 55 80 56 80 57 80 58 80 59 80 60 80 61 80 62 80 63 80 64 80
		 65 80 66 80 67 80 68 80 69 80 70 80 71 80 72 80 73 80 74 80 75 80 76 80 77 80 78 80
		 79 80 80 80;
createNode animCurveTL -n "front_right_suspension_DRV_translateY";
	rename -uid "A9AE60FA-46FE-DAD7-B707-9EA7BB1D542C";
	setAttr ".tan" 18;
	setAttr ".wgt" no;
	setAttr -s 80 ".ktv[0:79]"  1 27.312401477182966 2 27.282955828989607
		 3 27.19615239271031 4 27.05430668958531 5 26.859722796763045 6 26.614712420786482
		 7 26.321583453501326 8 26.038941451837182 9 25.787549087335229 10 25.50908000164187
		 11 25.181512140595338 12 25.050412439667603 13 24.910310053192994 14 24.777283607306899
		 15 24.86951535779518 16 24.965985236945571 17 25.23364629579023 18 25.612201593641792
		 19 26.102640670976598 20 26.766428512773473 21 27.503611708234622 22 28.420722151349857
		 23 29.346236372541263 24 30.490232883806094 25 31.604570804948672 26 32.82602510177226
		 27 34.038721177211713 28 35.240106733556289 29 36.448030622716445 30 37.537241447097344
		 31 38.640421378737969 32 39.537444342895917 33 40.449424018188886 34 41.142504394989437
		 35 41.801020325165219 36 42.297916385042605 37 42.672443362581667 38 43.026821109163699
		 39 43.100354147641305 40 43.191132498471383 41 43.19537856286582 42 43.035268089233007
		 43 42.868695518432226 44 42.515988249325332 45 42.073510069393691 46 41.555863072681248
		 47 40.850754430103123 48 40.136448458892268 49 39.214035586577815 50 38.307213800421408
		 51 37.239075677862814 52 36.181139743294047 53 35.056277072395609 54 33.934469974006937
		 55 32.83185201732207 56 31.752010403552539 57 30.741456736359879 58 29.794511545930192
		 59 28.941359986420103 60 28.199500550384947 61 27.54295038391701 62 27.05167841126076
		 63 26.595826259576633 64 26.369671932184055 65 26.151505580865695 66 26.105087414765485
		 67 26.125675335908063 68 26.151760235810407 69 26.367364164595905 70 26.563996549849811
		 71 26.746018644576374 72 27.03304980299928 73 27.306105833272717 74 27.547869901876233
		 75 27.756766538839123 76 27.931220274190686 77 28.13109150719032 78 28.268618973010632
		 79 28.352713974231335 80 28.381225021594616;
createNode animCurveTL -n "front_right_suspension_DRV_translateZ";
	rename -uid "6A70D720-4A66-BD22-BADB-41A016348089";
	setAttr ".tan" 18;
	setAttr ".wgt" no;
	setAttr -s 80 ".ktv[0:79]"  1 -180 2 -179.60814740981021 3 -178.4530753162316
		 4 -176.56551223475043 5 -173.97618668085283 6 -170.71582717002514 7 -166.81516221775348
		 8 -162.30492033952407 9 -157.21583005082317 10 -151.57861986713698 11 -145.42401830395164
		 12 -138.78275387675347 13 -131.68555510102863 14 -124.16315049226327 15 -116.24626856594372
		 16 -107.96563783755616 17 -99.351986822586753 18 -90.436044036521764 19 -81.248537994847396
		 20 -71.820197213049795 21 -62.181750206615277 22 -52.363925491030017 23 -42.397451581780217
		 24 -32.31305699435211 25 -22.141470244231868 26 -11.913419846905782 27 -1.6596343178599113
		 28 8.5891578274193989 29 18.802228073445917 30 28.948847904733526 31 38.998288805795909
		 32 48.919822261146948 33 58.682719755300411 34 68.256252772770125 35 77.609692798069659
		 36 86.712311315713066 37 95.533379810214058 38 104.04216976608632 39 112.2079526678437
		 40 120 41 127.77306170886035 42 135.88386075949296 43 144.30462816455596 44 153.00759493670756
		 45 161.9649920886061 46 171.14905063290968 47 180.53200158227659 48 190.08607594936507
		 49 199.78350474683327 50 209.59651898733958 51 219.49734968354201 52 229.45822784809891
		 53 239.45138449366857 54 249.44905063290906 55 259.42345727847862 56 269.34683544303573
		 57 279.1914161392383 58 288.92943037974464 59 298.53310917721313 60 307.9746835443018
		 61 317.226384493669 62 326.26044303797295 63 335.04909018987178 64 343.56455696202374
		 65 351.77907436708722 66 359.66487341772029 67 367.19418512658109 68 374.33924050632811
		 69 381.07227056961938 70 387.36550632911315 71 393.19117879746773 72 398.52151898734121
		 73 403.32875791139196 74 407.58512658227818 75 411.26285601265801 76 414.3341772151897
		 77 416.77132120253151 78 418.5465189873417 79 419.63200158227846 80 420;
createNode animCurveTA -n "front_right_suspension_DRV_rotateX";
	rename -uid "B4542AB4-4D72-74B8-26AC-00865E1FDD78";
	setAttr ".tan" 18;
	setAttr ".wgt" no;
	setAttr -s 80 ".ktv[0:79]"  1 4.3026510986433424 2 4.3026510986433424
		 3 4.3026510986433424 4 4.3026510986433424 5 4.3026510986433424 6 4.3026510986433424
		 7 4.3026510986433424 8 2.8667528645157709 9 2.8667528645157709 10 2.8667528645157709
		 11 1.2021997001270499 12 1.2021997001270499 13 1.2021997001270499 14 -0.56603206858416844
		 15 -0.56603206858416844 16 -0.56603206858416844 17 -2.3032946740052376 18 -2.3032946740052376
		 19 -3.8773748768618899 20 -3.8773748768618899 21 -5.1701535752175651 22 -5.1701535752175651
		 23 -5.1701535752175651 24 -6.0868374283011919 25 -6.0868374283011919 26 -6.5618502739053577
		 27 -6.5618502739053577 28 -6.5618511220823263 29 -6.5618511220823263 30 -6.0868382151167255
		 31 -6.0868382151167255 32 -5.1701551585373489 33 -5.1701551585373489 34 -3.8773783202619683
		 35 -3.8773783202619683 36 -2.3032973701597532 37 -2.3032973701597532 38 -2.3032973701597532
		 39 -0.56603327608835718 40 -0.56603327608835718 41 1.2021993082796105 42 1.2021993082796105
		 43 1.2021993082796105 44 2.8667466386911507 45 2.8667466386911507 46 4.3026506722424216
		 47 4.3026506722424216 48 5.405070156442088 49 5.405070156442088 50 6.0965832441646279
		 51 6.0965832441646279 52 6.3312315827082744 53 6.3312315827082744 54 6.3312315827082744
		 55 6.0961670751186103 56 6.0961670751186103 57 5.4118431183039863 58 5.4118431183039863
		 59 4.3311162246861956 60 4.3311162246861956 61 2.9368408605484917 62 2.9368408605484917
		 63 1.3370116731237118 64 1.3370116731237118 65 1.3370116731237118 66 -0.34315450866790675
		 67 -0.34315450866790675 68 -0.34315450866790675 69 -1.9718975325065522 70 -1.9718975325065522
		 71 -1.9718975325065522 72 -3.4227708226574971 73 -3.4227708226574971 74 -3.4227708226574971
		 75 -3.4227708226574971 76 -3.4227708226574971 77 -4.5856703946274724 78 -4.5856703946274724
		 79 -4.5856703946274724 80 -4.5856703946274724;
createNode animCurveTA -n "front_right_suspension_DRV_rotateY";
	rename -uid "3DE8B953-426F-8D92-B1E4-02B1906B8553";
	setAttr ".tan" 18;
	setAttr ".wgt" no;
	setAttr -s 80 ".ktv[0:79]"  1 6.2120208622334327e-18 2 6.2120208622334327e-18
		 3 6.2120208622334327e-18 4 6.2120208622334327e-18 5 6.2120208622334327e-18 6 6.2120208622334327e-18
		 7 6.2120208622334327e-18 8 3.1060104311167164e-18 9 3.1060104311167164e-18 10 3.1060104311167164e-18
		 11 0 12 0 13 0 14 0 15 0 16 0 17 0 18 0 19 -3.1060104311167164e-18 20 -3.1060104311167164e-18
		 21 0 22 0 23 0 24 -3.1060104311167156e-18 25 -3.1060104311167156e-18 26 0 27 0 28 0
		 29 0 30 0 31 0 32 -3.1060104311167156e-18 33 -3.1060104311167156e-18 34 0 35 0 36 0
		 37 0 38 0 39 0 40 0 41 -1.5530052155583582e-18 42 -1.5530052155583582e-18 43 -1.5530052155583582e-18
		 44 0 45 0 46 0 47 0 48 0 49 0 50 -6.2120208622334312e-18 51 -6.2120208622334312e-18
		 52 0 53 0 54 0 55 -6.2120208622334327e-18 56 -6.2120208622334327e-18 57 0 58 0 59 -3.1060104311167164e-18
		 60 -3.1060104311167164e-18 61 0 62 0 63 0 64 0 65 0 66 1.213285324654967e-20 67 1.213285324654967e-20
		 68 1.213285324654967e-20 69 0 70 0 71 0 72 0 73 0 74 0 75 0 76 0 77 3.1060104311167164e-18
		 78 3.1060104311167164e-18 79 3.1060104311167164e-18 80 3.1060104311167164e-18;
createNode animCurveTA -n "front_right_suspension_DRV_rotateZ";
	rename -uid "356362F9-4AEF-FFFC-64E9-9D8C22DCFA40";
	setAttr ".tan" 18;
	setAttr ".wgt" no;
	setAttr -s 80 ".ktv[0:79]"  1 -1.0264951741763964 2 -1.0264951741763964
		 3 -1.0264951741763964 4 -1.0264951741763964 5 -1.0264951741763964 6 -1.0264951741763964
		 7 -1.0264951741763964 8 -1.0039762461276578 9 -1.0039762461276578 10 -1.0039762461276578
		 11 -0.94860544597379814 12 -0.94860544597379814 13 -0.94860544597379814 14 -0.8621899417837845
		 15 -0.8621899417837845 16 -0.8621899417837845 17 -0.74755481722646411 18 -0.74755481722646411
		 19 -0.60844824133550768 20 -0.60844824133550768 21 -0.44942116918582525 22 -0.44942116918582525
		 23 -0.44942116918582525 24 -0.2756782847322275 25 -0.2756782847322275 26 -0.092906857962664333
		 27 -0.092906857962664333 28 0.092906878104909149 29 0.092906878104909149 30 0.27567787195487392
		 31 0.27567787195487392 32 0.4494210085623952 33 0.4494210085623952 34 0.60844804663192842
		 35 0.60844804663192842 36 0.74755550261247161 37 0.74755550261247161 38 0.74755550261247161
		 39 0.86219074017868425 40 0.86219074017868425 41 0.94860570961434787 42 0.94860570961434787
		 43 0.94860570961434787 44 1.0039778017877454 45 1.0039778017877454 46 1.0264957092071969
		 47 1.0264957092071969 48 1.0154221103627969 49 1.0154221103627969 50 0.97112523923934357
		 51 0.97112523923934357 52 0.89504707498006419 53 0.89504707498006419 54 0.89504707498006419
		 55 0.78967066374707795 56 0.78967066374707795 57 0.65845462981135139 58 0.65845462981135139
		 59 0.50567153837132028 60 0.50567153837132028 61 0.33633685836998967 62 0.33633685836998967
		 63 0.15598722036379689 64 0.15598722036379689 65 0.15598722036379689 66 -0.029470759956705121
		 67 -0.029470759956705121 68 -0.029470759956705121 69 -0.21396260119469465 70 -0.21396260119469465
		 71 -0.21396260119469465 72 -0.39144545246544732 73 -0.39144545246544732 74 -0.39144545246544732
		 75 -0.39144545246544732 76 -0.39144545246544732 77 -0.55611944381544798 78 -0.55611944381544798
		 79 -0.55611944381544798 80 -0.55611944381544798;
createNode animCurveTL -n "front_right_steer_DRV_translateX";
	rename -uid "74ACFC5E-409A-7602-3ADF-93A6E3A6C07D";
	setAttr ".tan" 18;
	setAttr ".wgt" no;
	setAttr -s 80 ".ktv[0:79]"  1 0 2 0 3 0 4 0 5 0 6 0 7 0 8 0 9 0 10 0
		 11 0 12 0 13 0 14 0 15 0 16 0 17 0 18 0 19 0 20 0 21 0 22 0 23 0 24 0 25 0 26 0 27 0
		 28 0 29 0 30 0 31 0 32 0 33 0 34 0 35 0 36 0 37 0 38 0 39 0 40 0 41 0 42 0 43 0 44 0
		 45 0 46 0 47 0 48 0 49 0 50 0 51 0 52 0 53 0 54 0 55 0 56 0 57 0 58 0 59 0 60 0 61 0
		 62 0 63 0 64 0 65 0 66 0 67 0 68 0 69 0 70 0 71 0 72 0 73 0 74 0 75 0 76 0 77 0 78 0
		 79 0 80 0;
createNode animCurveTL -n "front_right_steer_DRV_translateY";
	rename -uid "6A88F92F-4336-ABE1-5DF1-A18C6DF0C36D";
	setAttr ".tan" 18;
	setAttr ".wgt" no;
	setAttr -s 80 ".ktv[0:79]"  1 0 2 0 3 0 4 0 5 0 6 0 7 0 8 0 9 0 10 0
		 11 0 12 0 13 0 14 0 15 0 16 0 17 0 18 0 19 0 20 0 21 0 22 0 23 0 24 0 25 0 26 0 27 0
		 28 0 29 0 30 0 31 0 32 0 33 0 34 0 35 0 36 0 37 0 38 0 39 0 40 0 41 0 42 0 43 0 44 0
		 45 0 46 0 47 0 48 0 49 0 50 0 51 0 52 0 53 0 54 0 55 0 56 0 57 0 58 0 59 0 60 0 61 0
		 62 0 63 0 64 0 65 0 66 0 67 0 68 0 69 0 70 0 71 0 72 0 73 0 74 0 75 0 76 0 77 0 78 0
		 79 0 80 0;
createNode animCurveTL -n "front_right_steer_DRV_translateZ";
	rename -uid "273277EF-4F92-AFCB-640F-6985053B150C";
	setAttr ".tan" 18;
	setAttr ".wgt" no;
	setAttr -s 80 ".ktv[0:79]"  1 0 2 0 3 0 4 0 5 0 6 0 7 0 8 0 9 0 10 0
		 11 0 12 0 13 0 14 0 15 0 16 0 17 0 18 0 19 0 20 0 21 0 22 0 23 0 24 0 25 0 26 0 27 0
		 28 0 29 0 30 0 31 0 32 0 33 0 34 0 35 0 36 0 37 0 38 0 39 0 40 0 41 0 42 0 43 0 44 0
		 45 0 46 0 47 0 48 0 49 0 50 0 51 0 52 0 53 0 54 0 55 0 56 0 57 0 58 0 59 0 60 0 61 0
		 62 0 63 0 64 0 65 0 66 0 67 0 68 0 69 0 70 0 71 0 72 0 73 0 74 0 75 0 76 0 77 0 78 0
		 79 0 80 0;
createNode animCurveTA -n "front_right_steer_DRV_rotateX";
	rename -uid "7B1C2434-41B6-03C7-0E15-D48EB270C4AB";
	setAttr ".tan" 18;
	setAttr ".wgt" no;
	setAttr -s 80 ".ktv[0:79]"  1 0 2 0 3 0 4 0 5 0 6 0 7 0 8 0 9 0 10 0
		 11 0 12 0 13 0 14 0 15 0 16 0 17 0 18 0 19 0 20 0 21 0 22 0 23 0 24 0 25 0 26 0 27 0
		 28 0 29 0 30 0 31 0 32 0 33 0 34 0 35 0 36 0 37 0 38 0 39 0 40 0 41 0 42 0 43 0 44 0
		 45 0 46 0 47 0 48 0 49 0 50 0 51 0 52 0 53 0 54 0 55 0 56 0 57 0 58 0 59 0 60 0 61 0
		 62 0 63 0 64 0 65 0 66 0 67 0 68 0 69 0 70 0 71 0 72 0 73 0 74 0 75 0 76 0 77 0 78 0
		 79 0 80 0;
createNode animCurveTA -n "front_right_steer_DRV_rotateY";
	rename -uid "ECBA2BB5-49B5-EAFF-527D-77B27258B221";
	setAttr ".tan" 18;
	setAttr ".wgt" no;
	setAttr -s 80 ".ktv[0:79]"  1 0 2 0 3 0 4 0 5 0 6 0 7 0 8 0 9 0 10 0
		 11 0 12 0 13 0 14 0 15 0 16 0 17 0 18 0 19 0 20 0 21 0 22 0 23 0 24 0 25 0 26 0 27 0
		 28 0 29 0 30 0 31 0 32 0 33 0 34 0 35 0 36 0 37 0 38 0 39 0 40 0 41 0 42 0 43 0 44 0
		 45 0 46 0 47 0 48 0 49 0 50 0 51 0 52 0 53 0 54 0 55 0 56 0 57 0 58 0 59 0 60 0 61 0
		 62 0 63 0 64 0 65 0 66 0 67 0 68 0 69 0 70 0 71 0 72 0 73 0 74 0 75 0 76 0 77 0 78 0
		 79 0 80 0;
createNode animCurveTA -n "front_right_steer_DRV_rotateZ";
	rename -uid "8A5943E1-473E-6323-8F50-ADB8D4BEEEC9";
	setAttr ".tan" 18;
	setAttr ".wgt" no;
	setAttr -s 80 ".ktv[0:79]"  1 0 2 0 3 0 4 0 5 0 6 0 7 0 8 0 9 0 10 0
		 11 0 12 0 13 0 14 0 15 0 16 0 17 0 18 0 19 0 20 0 21 0 22 0 23 0 24 0 25 0 26 0 27 0
		 28 0 29 0 30 0 31 0 32 0 33 0 34 0 35 0 36 0 37 0 38 0 39 0 40 0 41 0 42 0 43 0 44 0
		 45 0 46 0 47 0 48 0 49 0 50 0 51 0 52 0 53 0 54 0 55 0 56 0 57 0 58 0 59 0 60 0 61 0
		 62 0 63 0 64 0 65 0 66 0 67 0 68 0 69 0 70 0 71 0 72 0 73 0 74 0 75 0 76 0 77 0 78 0
		 79 0 80 0;
createNode animCurveTL -n "front_right_spin_DRV_translateX";
	rename -uid "3F2B91D5-4B47-CB3D-D26B-D38AF2F2CA59";
	setAttr ".tan" 18;
	setAttr ".wgt" no;
	setAttr -s 80 ".ktv[0:79]"  1 0 2 0 3 0 4 0 5 0 6 0 7 0 8 0 9 0 10 0
		 11 0 12 0 13 0 14 0 15 0 16 0 17 0 18 0 19 0 20 0 21 0 22 0 23 0 24 0 25 0 26 0 27 0
		 28 0 29 0 30 0 31 0 32 0 33 0 34 0 35 0 36 0 37 0 38 0 39 0 40 0 41 0 42 0 43 0 44 0
		 45 0 46 0 47 0 48 0 49 0 50 0 51 0 52 0 53 0 54 0 55 0 56 0 57 0 58 0 59 0 60 0 61 0
		 62 0 63 0 64 0 65 0 66 0 67 0 68 0 69 0 70 0 71 0 72 0 73 0 74 0 75 0 76 0 77 0 78 0
		 79 0 80 0;
createNode animCurveTL -n "front_right_spin_DRV_translateY";
	rename -uid "0304850C-4C14-88FA-6562-65AEF7D69C08";
	setAttr ".tan" 18;
	setAttr ".wgt" no;
	setAttr -s 80 ".ktv[0:79]"  1 0 2 0 3 0 4 0 5 0 6 0 7 0 8 0 9 0 10 0
		 11 0 12 0 13 0 14 0 15 0 16 0 17 0 18 0 19 0 20 0 21 0 22 0 23 0 24 0 25 0 26 0 27 0
		 28 0 29 0 30 0 31 0 32 0 33 0 34 0 35 0 36 0 37 0 38 0 39 0 40 0 41 0 42 0 43 0 44 0
		 45 0 46 0 47 0 48 0 49 0 50 0 51 0 52 0 53 0 54 0 55 0 56 0 57 0 58 0 59 0 60 0 61 0
		 62 0 63 0 64 0 65 0 66 0 67 0 68 0 69 0 70 0 71 0 72 0 73 0 74 0 75 0 76 0 77 0 78 0
		 79 0 80 0;
createNode animCurveTL -n "front_right_spin_DRV_translateZ";
	rename -uid "4D0C8F7A-4BE2-2431-9458-7BB934796E3A";
	setAttr ".tan" 18;
	setAttr ".wgt" no;
	setAttr -s 80 ".ktv[0:79]"  1 0 2 0 3 0 4 0 5 0 6 0 7 0 8 0 9 0 10 0
		 11 0 12 0 13 0 14 0 15 0 16 0 17 0 18 0 19 0 20 0 21 0 22 0 23 0 24 0 25 0 26 0 27 0
		 28 0 29 0 30 0 31 0 32 0 33 0 34 0 35 0 36 0 37 0 38 0 39 0 40 0 41 0 42 0 43 0 44 0
		 45 0 46 0 47 0 48 0 49 0 50 0 51 0 52 0 53 0 54 0 55 0 56 0 57 0 58 0 59 0 60 0 61 0
		 62 0 63 0 64 0 65 0 66 0 67 0 68 0 69 0 70 0 71 0 72 0 73 0 74 0 75 0 76 0 77 0 78 0
		 79 0 80 0;
createNode animCurveTA -n "front_right_spin_DRV_rotateX";
	rename -uid "2A4379FE-417D-468E-A9DB-7D984E89092D";
	setAttr ".tan" 18;
	setAttr ".wgt" no;
	setAttr -s 80 ".ktv[0:79]"  1 0 2 0.66219937392232309 3 2.6141790920748651
		 4 5.8040096201819242 5 10.179762870608355 6 15.689509791291814 7 22.281321812383705
		 8 29.896750803396728 9 38.483184939732354 10 47.99442004039166 11 58.379025946463805
		 12 69.572856458324608 13 81.535162981973002 14 94.212742413965032 15 107.55491846166733
		 16 121.51011370796525 17 136.03232165854584 18 151.07069776844762 19 166.57524471526096
		 20 182.5028707314026 21 198.79267016379745 22 215.40932658153031 23 232.27673913066951
		 24 249.37779981929208 25 266.62113464035303 26 283.9789846458317 27 301.37869379189095
		 28 318.76786555159305 29 336.09849300108152 30 353.29540522253745 31 370.33207018739574
		 32 387.11918693913913 33 403.64287912344753 34 419.81776660615742 35 435.61886031085106
		 36 450.98115194190711 37 465.85950511592074 38 480.21067652265685 39 493.97019732954374
		 40 507.10199193895312 41 520.20068065429439 42 533.87140726550342 43 548.06459670791389
		 44 562.74242790426126 45 577.85556119349667 46 593.35651276369629 47 609.21294924770427
		 48 625.35728593093791 49 641.77283819301215 50 658.37930903067752 51 675.16066894468474
		 52 692.04076685160703 53 708.98723836932788 54 725.94069504258448 55 742.85161063229032
		 56 759.67285543847447 57 776.34978027974421 58 792.83733400563813 59 809.08478910014958
		 60 825.04441893507112 61 840.67388386428058 62 855.92022898993378 63 870.74893747989029
		 64 885.10393206451045 65 898.95159979423488 66 912.24069027641929 67 924.9288406059884
		 68 936.96952079600408 69 948.32084524327411 70 958.93113888822813 71 968.75312831810356
		 72 977.74846792906737 73 985.86250340822914 74 993.04673660293224 75 999.25429701977714
		 76 1004.4383141653644 77 1008.5588095668631 78 1011.559271510391 79 1013.3939681613595
		 80 1014.0159639987686;
createNode animCurveTA -n "front_right_spin_DRV_rotateY";
	rename -uid "7D1D24CA-4207-0334-1697-89A3A233A91A";
	setAttr ".tan" 18;
	setAttr ".wgt" no;
	setAttr -s 80 ".ktv[0:79]"  1 0 2 0 3 0 4 0 5 0 6 0 7 0 8 0 9 0 10 0
		 11 0 12 0 13 0 14 0 15 0 16 0 17 0 18 0 19 0 20 0 21 0 22 0 23 0 24 0 25 0 26 0 27 0
		 28 0 29 0 30 0 31 0 32 0 33 0 34 0 35 0 36 0 37 0 38 0 39 0 40 0 41 0 42 0 43 0 44 0
		 45 0 46 0 47 0 48 0 49 0 50 0 51 0 52 0 53 0 54 0 55 0 56 0 57 0 58 0 59 0 60 0 61 0
		 62 0 63 0 64 0 65 0 66 0 67 0 68 0 69 0 70 0 71 0 72 0 73 0 74 0 75 0 76 0 77 0 78 0
		 79 0 80 0;
createNode animCurveTA -n "front_right_spin_DRV_rotateZ";
	rename -uid "4E8199CF-4483-2CBD-6F7B-0395AC550469";
	setAttr ".tan" 18;
	setAttr ".wgt" no;
	setAttr -s 80 ".ktv[0:79]"  1 0 2 0 3 0 4 0 5 0 6 0 7 0 8 0 9 0 10 0
		 11 0 12 0 13 0 14 0 15 0 16 0 17 0 18 0 19 0 20 0 21 0 22 0 23 0 24 0 25 0 26 0 27 0
		 28 0 29 0 30 0 31 0 32 0 33 0 34 0 35 0 36 0 37 0 38 0 39 0 40 0 41 0 42 0 43 0 44 0
		 45 0 46 0 47 0 48 0 49 0 50 0 51 0 52 0 53 0 54 0 55 0 56 0 57 0 58 0 59 0 60 0 61 0
		 62 0 63 0 64 0 65 0 66 0 67 0 68 0 69 0 70 0 71 0 72 0 73 0 74 0 75 0 76 0 77 0 78 0
		 79 0 80 0;
createNode animCurveTL -n "rear_left_suspension_DRV_translateX";
	rename -uid "C79E19BC-4C0F-9B89-F9D2-DFB0B8EB34DD";
	setAttr ".tan" 18;
	setAttr ".wgt" no;
	setAttr -s 80 ".ktv[0:79]"  1 -80 2 -80 3 -80 4 -80 5 -80 6 -80 7 -80
		 8 -80 9 -80 10 -80 11 -80 12 -80 13 -80 14 -80 15 -80 16 -80 17 -80 18 -80 19 -80
		 20 -80 21 -80 22 -80 23 -80 24 -80 25 -80 26 -80 27 -80 28 -80 29 -80 30 -80 31 -80
		 32 -80 33 -80 34 -80 35 -80 36 -80 37 -80 38 -80 39 -80 40 -80 41 -80 42 -80 43 -80
		 44 -80 45 -80 46 -80 47 -80 48 -80 49 -80 50 -80 51 -80 52 -80 53 -80 54 -80 55 -80
		 56 -80 57 -80 58 -80 59 -80 60 -80 61 -80 62 -80 63 -80 64 -80 65 -80 66 -80 67 -80
		 68 -80 69 -80 70 -80 71 -80 72 -80 73 -80 74 -80 75 -80 76 -80 77 -80 78 -80 79 -80
		 80 -80;
createNode animCurveTL -n "rear_left_suspension_DRV_translateY";
	rename -uid "8512273B-47E4-05D4-B77B-92B52FBAAB90";
	setAttr ".tan" 18;
	setAttr ".wgt" no;
	setAttr -s 80 ".ktv[0:79]"  1 38.491673875692847 2 38.530610490683081
		 3 38.645398546103003 4 38.765116688765275 5 38.965128895796525 6 39.228846547163712
		 7 39.544356343306291 8 39.909167286909806 9 40.320803639448869 10 40.608556225622898
		 11 40.957677319372898 12 41.334397747839695 13 41.595638305844439 14 41.812095672787798
		 15 42.039901764096392 16 42.073323545196601 17 42.066354093292304 18 41.983501201717445
		 19 41.71003318413932 20 41.448777049527841 21 40.904404490934091 22 40.355599254117685
		 23 39.650857869613773 24 38.870916310775883 25 37.991436032400912 26 37.048030881033725
		 27 36.056641786241222 28 35.033936708116222 29 34.010097984192917 30 33.001442436097214
		 31 32.030917627790025 32 31.125869257428697 33 30.28317246737884 34 29.556022503999934
		 35 28.888034092126134 36 28.388461338219884 37 27.907753056903893 38 27.655590123554283
		 39 27.412876195331627 40 27.30868012305713 41 27.289206093516114 42 27.281750464410699
		 43 27.496075415582574 44 27.710118079156793 45 28.103474786504982 46 28.55731694959092
		 47 29.13650475688577 48 29.805175411182645 49 30.554213503259255 50 31.386534670251443
		 51 32.253332223354846 52 33.181665505825549 53 34.104314889370471 54 35.038187160350752
		 55 35.95910467133708 56 36.79692752596852 57 37.630560948820083 58 38.318297968782865
		 59 38.990439997591459 60 39.503972243542776 61 39.961152266736136 62 40.309574920510322
		 63 40.525727111672431 64 40.735161620949775 65 40.72553116627703 66 40.705778663835623
		 67 40.645935068972662 68 40.433559428103521 69 40.233432780154303 70 40.046599480841721
		 71 39.727057549689377 72 39.434516045783127 73 39.170683953497971 74 38.965919412210518
		 75 38.686729348733955 76 38.45344916684919 77 38.268340982034736 78 38.133506692483955
		 79 38.051059640482002 80 38.023109353616768;
createNode animCurveTL -n "rear_left_suspension_DRV_translateZ";
	rename -uid "7F7FD2F1-4156-A48D-8192-63B28607714B";
	setAttr ".tan" 18;
	setAttr ".wgt" no;
	setAttr -s 80 ".ktv[0:79]"  1 -420 2 -419.60814740981021 3 -418.4530753162316
		 4 -416.56551223475043 5 -413.97618668085283 6 -410.71582717002514 7 -406.81516221775348
		 8 -402.30492033952407 9 -397.21583005082317 10 -391.57861986713698 11 -385.42401830395164
		 12 -378.78275387675347 13 -371.68555510102863 14 -364.1631504922633 15 -356.24626856594375
		 16 -347.96563783755619 17 -339.35198682258675 18 -330.43604403652176 19 -321.24853799484742
		 20 -311.82019721304982 21 -302.18175020661528 22 -292.36392549103005 23 -282.39745158178022
		 24 -272.31305699435211 25 -262.14147024423187 26 -251.91341984690578 27 -241.65963431785991
		 28 -231.4108421725806 29 -221.19777192655408 30 -211.05115209526647 31 -201.00171119420409
		 32 -191.08017773885305 33 -181.31728024469959 34 -171.74374722722987 35 -162.39030720193034
		 36 -153.28768868428693 37 -144.46662018978594 38 -135.95783023391368 39 -127.7920473321563
		 40 -120 41 -112.22693829113965 42 -104.11613924050705 43 -95.695371835444035 44 -86.992405063292438
		 45 -78.035007911393919 46 -68.850949367090308 47 -59.467998417723415 48 -49.913924050634932
		 49 -40.216495253166727 50 -30.403481012660421 51 -20.502650316457988 52 -10.541772151901085
		 53 -0.54861550633141576 54 9.4490506329090636 55 19.423457278478651 56 29.346835443035729
		 57 39.191416139238271 58 48.929430379744645 59 58.533109177213134 60 67.974683544301826
		 61 77.226384493668974 62 86.260443037972948 63 95.049090189871748 64 103.56455696202374
		 65 111.77907436708725 66 119.66487341772026 67 127.19418512658109 68 134.33924050632814
		 69 141.07227056961938 70 147.36550632911315 71 153.19117879746773 72 158.52151898734121
		 73 163.32875791139196 74 167.58512658227818 75 171.26285601265801 76 174.3341772151897
		 77 176.77132120253151 78 178.5465189873417 79 179.63200158227846 80 180;
createNode animCurveTA -n "rear_left_suspension_DRV_rotateX";
	rename -uid "1BC0EF45-483F-C37A-13B4-48841F814FC7";
	setAttr ".tan" 18;
	setAttr ".wgt" no;
	setAttr -s 80 ".ktv[0:79]"  1 -5.5194736321252069 2 -5.5194736321252069
		 3 -5.5194736321252069 4 -4.4528193994879093 5 -4.4528193994879093 6 -4.4528193994879093
		 7 -4.4528193994879093 8 -4.4528193994879093 9 -4.4528193994879093 10 -3.0646560507906209
		 11 -3.0646560507906209 12 -3.0646560507906209 13 -1.4618579748578917 14 -1.4618579748578917
		 15 -1.4618579748578917 16 0.23077304895187634 17 0.23077304895187634 18 1.8810073758634545
		 19 1.8810073758634545 20 3.3611719587401954 21 3.3611719587401954 22 3.3611719587401954
		 23 4.5592595023803097 24 4.5592595023803097 25 5.3876352440939534 26 5.3876352440939534
		 27 5.7884422828429249 28 5.7884422828429249 29 5.7362907704571038 30 5.7362907704571038
		 31 5.2390050143347828 32 5.2390050143347828 33 4.3370812176945295 34 4.3370812176945295
		 35 3.1017387346666005 36 3.1017387346666005 37 1.6308654149057837 38 1.6308654149057837
		 39 1.6308654149057837 40 0.042142581832250996 41 0.042142581832250996 42 -1.5366003866972884
		 43 -1.5366003866972884 44 -1.5366003866972884 45 -2.9787883838179492 46 -2.9787883838179492
		 47 -4.1702753664443728 48 -4.1702753664443728 49 -5.0185837569463549 50 -5.0185837569463549
		 51 -5.4592272974708029 52 -5.4592272974708029 53 -5.4592272974708029 54 -5.4592281474264537
		 55 -5.4592281474264537 56 -5.0185855846099754 57 -5.0185855846099754 58 -4.1702753665661243
		 59 -4.1702753665661243 60 -2.978789094762063 61 -2.978789094762063 62 -1.5366042125012245
		 63 -1.5366042125012245 64 -1.5366042125012245 65 0.042140508295318513 66 0.042140508295318513
		 67 1.630862205154378 68 1.630862205154378 69 1.630862205154378 70 3.1017350844892717
		 71 3.1017350844892717 72 3.1017350844892717 73 3.1017350844892717 74 4.3370818982554429
		 75 4.3370818982554429 76 4.3370818982554429 77 4.3370818982554429 78 4.3370818982554429
		 79 4.3370818982554429 80 4.3370818982554429;
createNode animCurveTA -n "rear_left_suspension_DRV_rotateY";
	rename -uid "98F4D645-4390-04EF-C0F2-388B6F528935";
	setAttr ".tan" 18;
	setAttr ".wgt" no;
	setAttr -s 80 ".ktv[0:79]"  1 -3.1060104311167164e-18 2 -3.1060104311167164e-18
		 3 -3.1060104311167164e-18 4 -3.1060104311167171e-18 5 -3.1060104311167171e-18 6 -3.1060104311167171e-18
		 7 -3.1060104311167171e-18 8 -3.1060104311167171e-18 9 -3.1060104311167171e-18 10 0
		 11 0 12 0 13 0 14 0 15 0 16 4.8531412986198681e-20 17 4.8531412986198681e-20 18 0
		 19 0 20 0 21 0 22 0 23 3.1060104311167156e-18 24 3.1060104311167156e-18 25 -6.2120208622334312e-18
		 26 -6.2120208622334312e-18 27 0 28 0 29 0 30 0 31 0 32 0 33 -6.2120208622334296e-18
		 34 -6.2120208622334296e-18 35 -3.1060104311167171e-18 36 -3.1060104311167171e-18
		 37 0 38 0 39 0 40 0 41 0 42 0 43 0 44 0 45 0 46 0 47 -3.1060104311167152e-18 48 -3.1060104311167152e-18
		 49 0 50 0 51 7.765026077791789e-19 52 7.765026077791789e-19 53 7.765026077791789e-19
		 54 0 55 0 56 0 57 0 58 0 59 0 60 0 61 0 62 -1.5530052155583582e-18 63 -1.5530052155583582e-18
		 64 -1.5530052155583582e-18 65 0 66 0 67 0 68 0 69 0 70 -3.1060104311167164e-18 71 -3.1060104311167164e-18
		 72 -3.1060104311167164e-18 73 -3.1060104311167164e-18 74 0 75 0 76 0 77 0 78 0 79 0
		 80 0;
createNode animCurveTA -n "rear_left_suspension_DRV_rotateZ";
	rename -uid "219B9A2D-4A18-D6A3-5478-BFA3F8E10F11";
	setAttr ".tan" 18;
	setAttr ".wgt" no;
	setAttr -s 80 ".ktv[0:79]"  1 0.55611663030040115 2 0.55611663030040115
		 3 0.55611663030040115 4 0.39144630545213449 5 0.39144630545213449 6 0.39144630545213449
		 7 0.39144630545213449 8 0.39144630545213449 9 0.39144630545213449 10 0.2139661331498941
		 11 0.2139661331498941 12 0.2139661331498941 13 0.029471326273727925 14 0.029471326273727925
		 15 0.029471326273727925 16 -0.15598643430601067 17 -0.15598643430601067 18 -0.33633510741702283
		 19 -0.33633510741702283 20 -0.50567268108412744 21 -0.50567268108412744 22 -0.50567268108412744
		 23 -0.6584480107745958 24 -0.6584480107745958 25 -0.78967289230437288 26 -0.78967289230437288
		 27 -0.89504301929554964 28 -0.89504301929554964 29 -0.97112332517293543 30 -0.97112332517293543
		 31 -1.0154238276849981 32 -1.0154238276849981 33 -1.0264918764802351 34 -1.0264918764802351
		 35 -1.0039779736305723 36 -1.0039779736305723 37 -0.94860534602709645 38 -0.94860534602709645
		 39 -0.94860534602709645 40 -0.8621900483567797 41 -0.8621900483567797 42 -0.74755510585220786
		 43 -0.74755510585220786 44 -0.74755510585220786 45 -0.60844871207721096 46 -0.60844871207721096
		 47 -0.44942151071289721 48 -0.44942151071289721 49 -0.27567821815861537 50 -0.27567821815861537
		 51 -0.092907042925807246 52 -0.092907042925807246 53 -0.092907042925807246 54 0.092906687799799839
		 55 0.092906687799799839 56 0.27567782670464241 57 0.27567782670464241 58 0.44942129670944481
		 59 0.44942129670944481 60 0.60844847915759748 61 0.60844847915759748 62 0.74755424304107088
		 63 0.74755424304107088 64 0.74755424304107088 65 0.86219009581295181 66 0.86219009581295181
		 67 0.94860518908807134 68 0.94860518908807134 69 0.94860518908807134 70 1.0039765374907619
		 71 1.0039765374907619 72 1.0039765374907619 73 1.0039765374907619 74 1.0264943990898625
		 75 1.0264943990898625 76 1.0264943990898625 77 1.0264943990898625 78 1.0264943990898625
		 79 1.0264943990898625 80 1.0264943990898625;
createNode animCurveTL -n "rear_left_steer_DRV_translateX";
	rename -uid "7451AE5E-4DBF-02CE-117D-B98319B59723";
	setAttr ".tan" 18;
	setAttr ".wgt" no;
	setAttr -s 80 ".ktv[0:79]"  1 0 2 0 3 0 4 0 5 0 6 0 7 0 8 0 9 0 10 0
		 11 0 12 0 13 0 14 0 15 0 16 0 17 0 18 0 19 0 20 0 21 0 22 0 23 0 24 0 25 0 26 0 27 0
		 28 0 29 0 30 0 31 0 32 0 33 0 34 0 35 0 36 0 37 0 38 0 39 0 40 0 41 0 42 0 43 0 44 0
		 45 0 46 0 47 0 48 0 49 0 50 0 51 0 52 0 53 0 54 0 55 0 56 0 57 0 58 0 59 0 60 0 61 0
		 62 0 63 0 64 0 65 0 66 0 67 0 68 0 69 0 70 0 71 0 72 0 73 0 74 0 75 0 76 0 77 0 78 0
		 79 0 80 0;
createNode animCurveTL -n "rear_left_steer_DRV_translateY";
	rename -uid "16CF4CB9-474F-B1D2-5E80-24A47270FD3D";
	setAttr ".tan" 18;
	setAttr ".wgt" no;
	setAttr -s 80 ".ktv[0:79]"  1 0 2 0 3 0 4 0 5 0 6 0 7 0 8 0 9 0 10 0
		 11 0 12 0 13 0 14 0 15 0 16 0 17 0 18 0 19 0 20 0 21 0 22 0 23 0 24 0 25 0 26 0 27 0
		 28 0 29 0 30 0 31 0 32 0 33 0 34 0 35 0 36 0 37 0 38 0 39 0 40 0 41 0 42 0 43 0 44 0
		 45 0 46 0 47 0 48 0 49 0 50 0 51 0 52 0 53 0 54 0 55 0 56 0 57 0 58 0 59 0 60 0 61 0
		 62 0 63 0 64 0 65 0 66 0 67 0 68 0 69 0 70 0 71 0 72 0 73 0 74 0 75 0 76 0 77 0 78 0
		 79 0 80 0;
createNode animCurveTL -n "rear_left_steer_DRV_translateZ";
	rename -uid "721E4972-441A-AA21-E8C6-E6A7E7C5A063";
	setAttr ".tan" 18;
	setAttr ".wgt" no;
	setAttr -s 80 ".ktv[0:79]"  1 0 2 0 3 0 4 0 5 0 6 0 7 0 8 0 9 0 10 0
		 11 0 12 0 13 0 14 0 15 0 16 0 17 0 18 0 19 0 20 0 21 0 22 0 23 0 24 0 25 0 26 0 27 0
		 28 0 29 0 30 0 31 0 32 0 33 0 34 0 35 0 36 0 37 0 38 0 39 0 40 0 41 0 42 0 43 0 44 0
		 45 0 46 0 47 0 48 0 49 0 50 0 51 0 52 0 53 0 54 0 55 0 56 0 57 0 58 0 59 0 60 0 61 0
		 62 0 63 0 64 0 65 0 66 0 67 0 68 0 69 0 70 0 71 0 72 0 73 0 74 0 75 0 76 0 77 0 78 0
		 79 0 80 0;
createNode animCurveTA -n "rear_left_steer_DRV_rotateX";
	rename -uid "CDA1F3BD-4D64-90BE-F305-6EBECE6E802B";
	setAttr ".tan" 18;
	setAttr ".wgt" no;
	setAttr -s 80 ".ktv[0:79]"  1 0 2 0 3 0 4 0 5 0 6 0 7 0 8 0 9 0 10 0
		 11 0 12 0 13 0 14 0 15 0 16 0 17 0 18 0 19 0 20 0 21 0 22 0 23 0 24 0 25 0 26 0 27 0
		 28 0 29 0 30 0 31 0 32 0 33 0 34 0 35 0 36 0 37 0 38 0 39 0 40 0 41 0 42 0 43 0 44 0
		 45 0 46 0 47 0 48 0 49 0 50 0 51 0 52 0 53 0 54 0 55 0 56 0 57 0 58 0 59 0 60 0 61 0
		 62 0 63 0 64 0 65 0 66 0 67 0 68 0 69 0 70 0 71 0 72 0 73 0 74 0 75 0 76 0 77 0 78 0
		 79 0 80 0;
createNode animCurveTA -n "rear_left_steer_DRV_rotateY";
	rename -uid "66504567-45C2-9237-ACE7-0181AE199699";
	setAttr ".tan" 18;
	setAttr ".wgt" no;
	setAttr -s 80 ".ktv[0:79]"  1 0 2 0 3 0 4 0 5 0 6 0 7 0 8 0 9 0 10 0
		 11 0 12 0 13 0 14 0 15 0 16 0 17 0 18 0 19 0 20 0 21 0 22 0 23 0 24 0 25 0 26 0 27 0
		 28 0 29 0 30 0 31 0 32 0 33 0 34 0 35 0 36 0 37 0 38 0 39 0 40 0 41 0 42 0 43 0 44 0
		 45 0 46 0 47 0 48 0 49 0 50 0 51 0 52 0 53 0 54 0 55 0 56 0 57 0 58 0 59 0 60 0 61 0
		 62 0 63 0 64 0 65 0 66 0 67 0 68 0 69 0 70 0 71 0 72 0 73 0 74 0 75 0 76 0 77 0 78 0
		 79 0 80 0;
createNode animCurveTA -n "rear_left_steer_DRV_rotateZ";
	rename -uid "133A8592-436C-169E-5385-B39063BB0DCF";
	setAttr ".tan" 18;
	setAttr ".wgt" no;
	setAttr -s 80 ".ktv[0:79]"  1 0 2 0 3 0 4 0 5 0 6 0 7 0 8 0 9 0 10 0
		 11 0 12 0 13 0 14 0 15 0 16 0 17 0 18 0 19 0 20 0 21 0 22 0 23 0 24 0 25 0 26 0 27 0
		 28 0 29 0 30 0 31 0 32 0 33 0 34 0 35 0 36 0 37 0 38 0 39 0 40 0 41 0 42 0 43 0 44 0
		 45 0 46 0 47 0 48 0 49 0 50 0 51 0 52 0 53 0 54 0 55 0 56 0 57 0 58 0 59 0 60 0 61 0
		 62 0 63 0 64 0 65 0 66 0 67 0 68 0 69 0 70 0 71 0 72 0 73 0 74 0 75 0 76 0 77 0 78 0
		 79 0 80 0;
createNode animCurveTL -n "rear_left_spin_DRV_translateX";
	rename -uid "1E8777D1-4839-1876-B940-85867EC2B381";
	setAttr ".tan" 18;
	setAttr ".wgt" no;
	setAttr -s 80 ".ktv[0:79]"  1 0 2 0 3 0 4 0 5 0 6 0 7 0 8 0 9 0 10 0
		 11 0 12 0 13 0 14 0 15 0 16 0 17 0 18 0 19 0 20 0 21 0 22 0 23 0 24 0 25 0 26 0 27 0
		 28 0 29 0 30 0 31 0 32 0 33 0 34 0 35 0 36 0 37 0 38 0 39 0 40 0 41 0 42 0 43 0 44 0
		 45 0 46 0 47 0 48 0 49 0 50 0 51 0 52 0 53 0 54 0 55 0 56 0 57 0 58 0 59 0 60 0 61 0
		 62 0 63 0 64 0 65 0 66 0 67 0 68 0 69 0 70 0 71 0 72 0 73 0 74 0 75 0 76 0 77 0 78 0
		 79 0 80 0;
createNode animCurveTL -n "rear_left_spin_DRV_translateY";
	rename -uid "A4BDB04C-4AD2-6DDC-DF61-598C24806D5B";
	setAttr ".tan" 18;
	setAttr ".wgt" no;
	setAttr -s 80 ".ktv[0:79]"  1 0 2 0 3 0 4 0 5 0 6 0 7 0 8 0 9 0 10 0
		 11 0 12 0 13 0 14 0 15 0 16 0 17 0 18 0 19 0 20 0 21 0 22 0 23 0 24 0 25 0 26 0 27 0
		 28 0 29 0 30 0 31 0 32 0 33 0 34 0 35 0 36 0 37 0 38 0 39 0 40 0 41 0 42 0 43 0 44 0
		 45 0 46 0 47 0 48 0 49 0 50 0 51 0 52 0 53 0 54 0 55 0 56 0 57 0 58 0 59 0 60 0 61 0
		 62 0 63 0 64 0 65 0 66 0 67 0 68 0 69 0 70 0 71 0 72 0 73 0 74 0 75 0 76 0 77 0 78 0
		 79 0 80 0;
createNode animCurveTL -n "rear_left_spin_DRV_translateZ";
	rename -uid "CEE99B7C-4A60-9C91-8235-EF8B3698A9FF";
	setAttr ".tan" 18;
	setAttr ".wgt" no;
	setAttr -s 80 ".ktv[0:79]"  1 0 2 0 3 0 4 0 5 0 6 0 7 0 8 0 9 0 10 0
		 11 0 12 0 13 0 14 0 15 0 16 0 17 0 18 0 19 0 20 0 21 0 22 0 23 0 24 0 25 0 26 0 27 0
		 28 0 29 0 30 0 31 0 32 0 33 0 34 0 35 0 36 0 37 0 38 0 39 0 40 0 41 0 42 0 43 0 44 0
		 45 0 46 0 47 0 48 0 49 0 50 0 51 0 52 0 53 0 54 0 55 0 56 0 57 0 58 0 59 0 60 0 61 0
		 62 0 63 0 64 0 65 0 66 0 67 0 68 0 69 0 70 0 71 0 72 0 73 0 74 0 75 0 76 0 77 0 78 0
		 79 0 80 0;
createNode animCurveTA -n "rear_left_spin_DRV_rotateX";
	rename -uid "CBCE2EF0-48DB-9FE2-8BB4-4E8891BBC1CA";
	setAttr ".tan" 18;
	setAttr ".wgt" no;
	setAttr -s 80 ".ktv[0:79]"  1 0 2 0.66358741059282533 3 2.6196601633353649
		 4 5.8060216647081102 5 10.182472420166008 6 15.694650847937437 7 22.289371854881363
		 8 29.9146830716934 9 38.518634125382981 10 48.029645245913791 11 58.417815582178029
		 12 69.627409198127651 13 81.595451133671375 14 94.277161516274788 15 107.62390476903012
		 16 121.57797492198435 17 136.09337064362686 18 151.1182713861441 19 166.60756437991037
		 20 182.49943180166275 21 198.76769564310607 22 215.33815936483413 23 232.17527562058615
		 24 249.219889737019 25 266.4246833993509 26 283.73380006250778 27 301.09371877601632
		 28 318.45040891568931 29 335.7474064168527 30 352.93042902492238 31 369.94421051896035
		 32 386.73307611178905 33 403.24632063321718 34 419.42580527674585 35 435.22775325572474
		 36 450.59028648330326 37 465.47605221856122 38 479.82109356038643 39 493.58789073763631
		 40 506.71997870915681 41 519.81892958958474 42 533.48567853294105 43 547.68068437715613
		 44 562.3510603601004 45 577.46019148158825 46 592.9557214235025 47 608.79767735419443
		 48 624.9372297214959 49 641.32764139457788 50 657.92354003040919 51 674.67179923818139
		 52 691.53026710887832 53 708.44197172409497 54 725.36304061556757 55 742.24301395359271
		 56 759.02465241762388 57 775.67373541275401 58 792.12404609511339 59 808.34739442965838
		 60 824.28105076859697 61 839.89070793013855 62 855.12594347119068 63 869.94074885364603
		 64 884.29506086613026 65 898.13653020211075 66 911.42546296004309 67 924.11375291623551
		 68 936.15969264270416 69 947.51099354389919 70 958.12011983106004 71 967.95211857117602
		 72 976.94815945860228 73 985.06135977687245 74 992.24133748119152 75 998.45676339485703
		 76 1003.6473648900959 77 1007.766192269992 78 1010.7663162523547 79 1012.6008060967987
		 80 1013.2227315490036;
createNode animCurveTA -n "rear_left_spin_DRV_rotateY";
	rename -uid "8DC78FC6-4E46-F37B-194B-348D31A7A272";
	setAttr ".tan" 18;
	setAttr ".wgt" no;
	setAttr -s 80 ".ktv[0:79]"  1 0 2 0 3 0 4 0 5 0 6 0 7 0 8 0 9 0 10 0
		 11 0 12 0 13 0 14 0 15 0 16 0 17 0 18 0 19 0 20 0 21 0 22 0 23 0 24 0 25 0 26 0 27 0
		 28 0 29 0 30 0 31 0 32 0 33 0 34 0 35 0 36 0 37 0 38 0 39 0 40 0 41 0 42 0 43 0 44 0
		 45 0 46 0 47 0 48 0 49 0 50 0 51 0 52 0 53 0 54 0 55 0 56 0 57 0 58 0 59 0 60 0 61 0
		 62 0 63 0 64 0 65 0 66 0 67 0 68 0 69 0 70 0 71 0 72 0 73 0 74 0 75 0 76 0 77 0 78 0
		 79 0 80 0;
createNode animCurveTA -n "rear_left_spin_DRV_rotateZ";
	rename -uid "27FF1194-4668-178B-B29B-4DA403B39305";
	setAttr ".tan" 18;
	setAttr ".wgt" no;
	setAttr -s 80 ".ktv[0:79]"  1 0 2 0 3 0 4 0 5 0 6 0 7 0 8 0 9 0 10 0
		 11 0 12 0 13 0 14 0 15 0 16 0 17 0 18 0 19 0 20 0 21 0 22 0 23 0 24 0 25 0 26 0 27 0
		 28 0 29 0 30 0 31 0 32 0 33 0 34 0 35 0 36 0 37 0 38 0 39 0 40 0 41 0 42 0 43 0 44 0
		 45 0 46 0 47 0 48 0 49 0 50 0 51 0 52 0 53 0 54 0 55 0 56 0 57 0 58 0 59 0 60 0 61 0
		 62 0 63 0 64 0 65 0 66 0 67 0 68 0 69 0 70 0 71 0 72 0 73 0 74 0 75 0 76 0 77 0 78 0
		 79 0 80 0;
createNode animCurveTL -n "rear_right_suspension_DRV_translateX";
	rename -uid "F321F4A0-4554-698C-9162-CD8F4918886A";
	setAttr ".tan" 18;
	setAttr ".wgt" no;
	setAttr -s 80 ".ktv[0:79]"  1 80 2 80 3 80 4 80 5 80 6 80 7 80 8 80
		 9 80 10 80 11 80 12 80 13 80 14 80 15 80 16 80 17 80 18 80 19 80 20 80 21 80 22 80
		 23 80 24 80 25 80 26 80 27 80 28 80 29 80 30 80 31 80 32 80 33 80 34 80 35 80 36 80
		 37 80 38 80 39 80 40 80 41 80 42 80 43 80 44 80 45 80 46 80 47 80 48 80 49 80 50 80
		 51 80 52 80 53 80 54 80 55 80 56 80 57 80 58 80 59 80 60 80 61 80 62 80 63 80 64 80
		 65 80 66 80 67 80 68 80 69 80 70 80 71 80 72 80 73 80 74 80 75 80 76 80 77 80 78 80
		 79 80 80 80;
createNode animCurveTL -n "rear_right_suspension_DRV_translateY";
	rename -uid "C2C2C390-4759-B13A-9930-3BA04FA64B8F";
	setAttr ".tan" 18;
	setAttr ".wgt" no;
	setAttr -s 80 ".ktv[0:79]"  1 39.84036198363043 2 39.870719344470274
		 3 39.960208327624571 4 40.055110329635006 5 40.202185982711178 6 40.387378090865475
		 7 40.608935708052975 8 40.865119332320553 9 41.155894631392819 10 41.334512040358064
		 11 41.526814744215486 12 41.734319016676423 13 41.85242476517616 14 41.872989798135144
		 15 41.894638205117566 16 41.755257687762388 17 41.526494107440122 18 41.255737930675146
		 19 40.756119400401708 20 40.294467450407907 21 39.542731763152048 22 38.771304608611032
		 23 37.879285353131991 24 36.8986602005441 25 35.857341751568853 26 34.743568405621588
		 27 33.617918746612311 28 32.464281814239264 29 31.340973994493964 30 30.246319911242011
		 31 29.216271081194243 32 28.272545495256743 33 27.411392871225935 34 26.691960040415388
		 35 26.043160507012963 36 25.593506881524682 37 25.162614130341431 38 24.994645380341431
		 39 24.833447717987916 40 24.825783668342055 41 24.916340766730727 42 25.031368158583199
		 43 25.388900659803902 44 25.758411310438667 45 26.328882736406285 46 26.975477737626989
		 47 27.7571097856272 48 28.649584913801029 49 29.622633396501406 50 30.699858127946719
		 51 31.81015596114726 52 32.988252732387494 53 34.162916276088666 54 35.341806562657851
		 55 36.51983848404457 56 37.580931174880547 57 38.661619651443047 58 39.538340796753339
		 59 40.435446967407636 60 41.122679413299984 61 41.774035156708187 62 42.278728457796511
		 63 42.651878329622683 64 43.008678408968386 65 43.095356894223336 66 43.187226248471383
		 67 43.206807395873632 68 43.065758964477148 69 42.932847282348241 70 42.794697660946426
		 71 42.506920713924941 72 42.243611235165176 73 42.006142515682754 74 41.823685338306248
		 75 41.547310521411717 76 41.316506078052342 77 41.133362462329686 78 40.999958684253514
		 79 40.918385197925389 80 40.890732457446873;
createNode animCurveTL -n "rear_right_suspension_DRV_translateZ";
	rename -uid "5D67E75D-4F81-09EE-7839-0F9AA1B8DC04";
	setAttr ".tan" 18;
	setAttr ".wgt" no;
	setAttr -s 80 ".ktv[0:79]"  1 -420 2 -419.60814740981021 3 -418.4530753162316
		 4 -416.56551223475043 5 -413.97618668085283 6 -410.71582717002514 7 -406.81516221775348
		 8 -402.30492033952407 9 -397.21583005082317 10 -391.57861986713698 11 -385.42401830395164
		 12 -378.78275387675347 13 -371.68555510102863 14 -364.1631504922633 15 -356.24626856594375
		 16 -347.96563783755619 17 -339.35198682258675 18 -330.43604403652176 19 -321.24853799484742
		 20 -311.82019721304982 21 -302.18175020661528 22 -292.36392549103005 23 -282.39745158178022
		 24 -272.31305699435211 25 -262.14147024423187 26 -251.91341984690578 27 -241.65963431785991
		 28 -231.4108421725806 29 -221.19777192655408 30 -211.05115209526647 31 -201.00171119420409
		 32 -191.08017773885305 33 -181.31728024469959 34 -171.74374722722987 35 -162.39030720193034
		 36 -153.28768868428693 37 -144.46662018978594 38 -135.95783023391368 39 -127.7920473321563
		 40 -120 41 -112.22693829113965 42 -104.11613924050705 43 -95.695371835444035 44 -86.992405063292438
		 45 -78.035007911393919 46 -68.850949367090308 47 -59.467998417723415 48 -49.913924050634932
		 49 -40.216495253166727 50 -30.403481012660421 51 -20.502650316457988 52 -10.541772151901085
		 53 -0.54861550633141576 54 9.4490506329090636 55 19.423457278478651 56 29.346835443035729
		 57 39.191416139238271 58 48.929430379744645 59 58.533109177213134 60 67.974683544301826
		 61 77.226384493668974 62 86.260443037972948 63 95.049090189871748 64 103.56455696202374
		 65 111.77907436708725 66 119.66487341772026 67 127.19418512658109 68 134.33924050632814
		 69 141.07227056961938 70 147.36550632911315 71 153.19117879746773 72 158.52151898734121
		 73 163.32875791139196 74 167.58512658227818 75 171.26285601265801 76 174.3341772151897
		 77 176.77132120253151 78 178.5465189873417 79 179.63200158227846 80 180;
createNode animCurveTA -n "rear_right_suspension_DRV_rotateX";
	rename -uid "FEC47BE8-49C3-5A68-9E99-A5B286CB560A";
	setAttr ".tan" 18;
	setAttr ".wgt" no;
	setAttr -s 80 ".ktv[0:79]"  1 -4.5856712512581099 2 -4.5856712512581099
		 3 -4.5856712512581099 4 -3.4227740167148908 5 -3.4227740167148908 6 -3.4227740167148908
		 7 -3.4227740167148908 8 -3.4227740167148908 9 -3.4227740167148908 10 -1.9718997613050859
		 11 -1.9718997613050859 12 -1.9718997613050859 13 -0.34315702280777904 14 -0.34315702280777904
		 15 -0.34315702280777904 16 1.3370096460124852 17 1.3370096460124852 18 2.9368383028885199
		 19 2.9368383028885199 20 4.3311163919216531 21 4.3311163919216531 22 4.3311163919216531
		 23 5.4118402539064983 24 5.4118402539064983 25 6.0961662295312582 26 6.0961662295312582
		 27 6.3312311084930686 28 6.3312311084930686 29 6.0965849393650489 30 6.0965849393650489
		 31 5.4050714298049396 32 5.4050714298049396 33 4.3026510986433424 34 4.3026510986433424
		 35 2.8667528645157709 36 2.8667528645157709 37 1.2021997001270499 38 1.2021997001270499
		 39 1.2021997001270499 40 -0.56603206858416844 41 -0.56603206858416844 42 -2.3032946740052376
		 43 -2.3032946740052376 44 -2.3032946740052376 45 -3.8773748768618899 46 -3.8773748768618899
		 47 -5.1701535752175651 48 -5.1701535752175651 49 -6.0868374283011919 50 -6.0868374283011919
		 51 -6.5618502739053577 52 -6.5618502739053577 53 -6.5618502739053577 54 -6.5618511220823263
		 55 -6.5618511220823263 56 -6.0868382151167255 57 -6.0868382151167255 58 -5.1701551585373489
		 59 -5.1701551585373489 60 -3.8773783202619683 61 -3.8773783202619683 62 -2.3032973701597532
		 63 -2.3032973701597532 64 -2.3032973701597532 65 -0.56603327608835718 66 -0.56603327608835718
		 67 1.2021993082796105 68 1.2021993082796105 69 1.2021993082796105 70 2.8667466386911507
		 71 2.8667466386911507 72 2.8667466386911507 73 2.8667466386911507 74 4.3026506722424216
		 75 4.3026506722424216 76 4.3026506722424216 77 4.3026506722424216 78 4.3026506722424216
		 79 4.3026506722424216 80 4.3026506722424216;
createNode animCurveTA -n "rear_right_suspension_DRV_rotateY";
	rename -uid "04A8D517-4030-8DBE-10C5-24992099FFDD";
	setAttr ".tan" 18;
	setAttr ".wgt" no;
	setAttr -s 80 ".ktv[0:79]"  1 -3.1060104311167156e-18 2 -3.1060104311167156e-18
		 3 -3.1060104311167156e-18 4 -1.5530052155583578e-18 5 -1.5530052155583578e-18 6 -1.5530052155583578e-18
		 7 -1.5530052155583578e-18 8 -1.5530052155583578e-18 9 -1.5530052155583578e-18 10 -7.765026077791789e-19
		 11 -7.765026077791789e-19 12 -7.765026077791789e-19 13 0 14 0 15 0 16 3.8825130388958955e-19
		 17 3.8825130388958955e-19 18 0 19 0 20 -3.1060104311167148e-18 21 -3.1060104311167148e-18
		 22 -3.1060104311167148e-18 23 -6.2120208622334304e-18 24 -6.2120208622334304e-18
		 25 -6.2120208622334327e-18 26 -6.2120208622334327e-18 27 0 28 0 29 0 30 0 31 6.2120208622334343e-18
		 32 6.2120208622334343e-18 33 6.2120208622334327e-18 34 6.2120208622334327e-18 35 3.1060104311167164e-18
		 36 3.1060104311167164e-18 37 0 38 0 39 0 40 0 41 0 42 0 43 0 44 0 45 -3.1060104311167164e-18
		 46 -3.1060104311167164e-18 47 0 48 0 49 -3.1060104311167156e-18 50 -3.1060104311167156e-18
		 51 0 52 0 53 0 54 0 55 0 56 0 57 0 58 -3.1060104311167156e-18 59 -3.1060104311167156e-18
		 60 0 61 0 62 0 63 0 64 0 65 0 66 0 67 -1.5530052155583582e-18 68 -1.5530052155583582e-18
		 69 -1.5530052155583582e-18 70 0 71 0 72 0 73 0 74 0 75 0 76 0 77 0 78 0 79 0 80 0;
createNode animCurveTA -n "rear_right_suspension_DRV_rotateZ";
	rename -uid "471E11FB-4078-87B7-053B-0F88305F9962";
	setAttr ".tan" 18;
	setAttr ".wgt" no;
	setAttr -s 80 ".ktv[0:79]"  1 0.55611221730653893 2 0.55611221730653893
		 3 0.55611221730653893 4 0.39145007631979151 5 0.39145007631979151 6 0.39145007631979151
		 7 0.39145007631979151 8 0.39145007631979151 9 0.39145007631979151 10 0.21396397662847944
		 11 0.21396397662847944 12 0.21396397662847944 13 0.029471305158555117 14 0.029471305158555117
		 15 0.029471305158555117 16 -0.15598644642358095 17 -0.15598644642358095 18 -0.33633586991303205
		 19 -0.33633586991303205 20 -0.50567231081887387 21 -0.50567231081887387 22 -0.50567231081887387
		 23 -0.6584475692833992 24 -0.6584475692833992 25 -0.78966835640035604 26 -0.78966835640035604
		 27 -0.89504841701616256 28 -0.89504841701616256 29 -0.97112674162565404 30 -0.97112674162565404
		 31 -1.0154230749964515 32 -1.0154230749964515 33 -1.0264951741763964 34 -1.0264951741763964
		 35 -1.0039762461276578 36 -1.0039762461276578 37 -0.94860544597379814 38 -0.94860544597379814
		 39 -0.94860544597379814 40 -0.8621899417837845 41 -0.8621899417837845 42 -0.74755481722646411
		 43 -0.74755481722646411 44 -0.74755481722646411 45 -0.60844824133550768 46 -0.60844824133550768
		 47 -0.44942116918582525 48 -0.44942116918582525 49 -0.2756782847322275 50 -0.2756782847322275
		 51 -0.092906857962664333 52 -0.092906857962664333 53 -0.092906857962664333 54 0.092906878104909149
		 55 0.092906878104909149 56 0.27567787195487392 57 0.27567787195487392 58 0.4494210085623952
		 59 0.4494210085623952 60 0.60844804663192842 61 0.60844804663192842 62 0.74755550261247161
		 63 0.74755550261247161 64 0.74755550261247161 65 0.86219074017868425 66 0.86219074017868425
		 67 0.94860570961434787 68 0.94860570961434787 69 0.94860570961434787 70 1.0039778017877454
		 71 1.0039778017877454 72 1.0039778017877454 73 1.0039778017877454 74 1.0264957092071969
		 75 1.0264957092071969 76 1.0264957092071969 77 1.0264957092071969 78 1.0264957092071969
		 79 1.0264957092071969 80 1.0264957092071969;
createNode animCurveTL -n "rear_right_steer_DRV_translateX";
	rename -uid "0B0A6532-4CD3-F6B9-8F44-28ABE7AE2EE6";
	setAttr ".tan" 18;
	setAttr ".wgt" no;
	setAttr -s 80 ".ktv[0:79]"  1 0 2 0 3 0 4 0 5 0 6 0 7 0 8 0 9 0 10 0
		 11 0 12 0 13 0 14 0 15 0 16 0 17 0 18 0 19 0 20 0 21 0 22 0 23 0 24 0 25 0 26 0 27 0
		 28 0 29 0 30 0 31 0 32 0 33 0 34 0 35 0 36 0 37 0 38 0 39 0 40 0 41 0 42 0 43 0 44 0
		 45 0 46 0 47 0 48 0 49 0 50 0 51 0 52 0 53 0 54 0 55 0 56 0 57 0 58 0 59 0 60 0 61 0
		 62 0 63 0 64 0 65 0 66 0 67 0 68 0 69 0 70 0 71 0 72 0 73 0 74 0 75 0 76 0 77 0 78 0
		 79 0 80 0;
createNode animCurveTL -n "rear_right_steer_DRV_translateY";
	rename -uid "F17A55AE-4C07-21E9-0ECE-5B8A027037A7";
	setAttr ".tan" 18;
	setAttr ".wgt" no;
	setAttr -s 80 ".ktv[0:79]"  1 0 2 0 3 0 4 0 5 0 6 0 7 0 8 0 9 0 10 0
		 11 0 12 0 13 0 14 0 15 0 16 0 17 0 18 0 19 0 20 0 21 0 22 0 23 0 24 0 25 0 26 0 27 0
		 28 0 29 0 30 0 31 0 32 0 33 0 34 0 35 0 36 0 37 0 38 0 39 0 40 0 41 0 42 0 43 0 44 0
		 45 0 46 0 47 0 48 0 49 0 50 0 51 0 52 0 53 0 54 0 55 0 56 0 57 0 58 0 59 0 60 0 61 0
		 62 0 63 0 64 0 65 0 66 0 67 0 68 0 69 0 70 0 71 0 72 0 73 0 74 0 75 0 76 0 77 0 78 0
		 79 0 80 0;
createNode animCurveTL -n "rear_right_steer_DRV_translateZ";
	rename -uid "42333338-4D22-49FB-7A2C-12B4CF76C74B";
	setAttr ".tan" 18;
	setAttr ".wgt" no;
	setAttr -s 80 ".ktv[0:79]"  1 0 2 0 3 0 4 0 5 0 6 0 7 0 8 0 9 0 10 0
		 11 0 12 0 13 0 14 0 15 0 16 0 17 0 18 0 19 0 20 0 21 0 22 0 23 0 24 0 25 0 26 0 27 0
		 28 0 29 0 30 0 31 0 32 0 33 0 34 0 35 0 36 0 37 0 38 0 39 0 40 0 41 0 42 0 43 0 44 0
		 45 0 46 0 47 0 48 0 49 0 50 0 51 0 52 0 53 0 54 0 55 0 56 0 57 0 58 0 59 0 60 0 61 0
		 62 0 63 0 64 0 65 0 66 0 67 0 68 0 69 0 70 0 71 0 72 0 73 0 74 0 75 0 76 0 77 0 78 0
		 79 0 80 0;
createNode animCurveTA -n "rear_right_steer_DRV_rotateX";
	rename -uid "55B1AD67-4382-C9E1-6CA3-FAA58B0F3E7E";
	setAttr ".tan" 18;
	setAttr ".wgt" no;
	setAttr -s 80 ".ktv[0:79]"  1 0 2 0 3 0 4 0 5 0 6 0 7 0 8 0 9 0 10 0
		 11 0 12 0 13 0 14 0 15 0 16 0 17 0 18 0 19 0 20 0 21 0 22 0 23 0 24 0 25 0 26 0 27 0
		 28 0 29 0 30 0 31 0 32 0 33 0 34 0 35 0 36 0 37 0 38 0 39 0 40 0 41 0 42 0 43 0 44 0
		 45 0 46 0 47 0 48 0 49 0 50 0 51 0 52 0 53 0 54 0 55 0 56 0 57 0 58 0 59 0 60 0 61 0
		 62 0 63 0 64 0 65 0 66 0 67 0 68 0 69 0 70 0 71 0 72 0 73 0 74 0 75 0 76 0 77 0 78 0
		 79 0 80 0;
createNode animCurveTA -n "rear_right_steer_DRV_rotateY";
	rename -uid "D3E5DD25-4052-6F38-22D0-30AD515621AC";
	setAttr ".tan" 18;
	setAttr ".wgt" no;
	setAttr -s 80 ".ktv[0:79]"  1 0 2 0 3 0 4 0 5 0 6 0 7 0 8 0 9 0 10 0
		 11 0 12 0 13 0 14 0 15 0 16 0 17 0 18 0 19 0 20 0 21 0 22 0 23 0 24 0 25 0 26 0 27 0
		 28 0 29 0 30 0 31 0 32 0 33 0 34 0 35 0 36 0 37 0 38 0 39 0 40 0 41 0 42 0 43 0 44 0
		 45 0 46 0 47 0 48 0 49 0 50 0 51 0 52 0 53 0 54 0 55 0 56 0 57 0 58 0 59 0 60 0 61 0
		 62 0 63 0 64 0 65 0 66 0 67 0 68 0 69 0 70 0 71 0 72 0 73 0 74 0 75 0 76 0 77 0 78 0
		 79 0 80 0;
createNode animCurveTA -n "rear_right_steer_DRV_rotateZ";
	rename -uid "E5E80183-46D7-FBFA-4EC2-7DB5DC8AA942";
	setAttr ".tan" 18;
	setAttr ".wgt" no;
	setAttr -s 80 ".ktv[0:79]"  1 0 2 0 3 0 4 0 5 0 6 0 7 0 8 0 9 0 10 0
		 11 0 12 0 13 0 14 0 15 0 16 0 17 0 18 0 19 0 20 0 21 0 22 0 23 0 24 0 25 0 26 0 27 0
		 28 0 29 0 30 0 31 0 32 0 33 0 34 0 35 0 36 0 37 0 38 0 39 0 40 0 41 0 42 0 43 0 44 0
		 45 0 46 0 47 0 48 0 49 0 50 0 51 0 52 0 53 0 54 0 55 0 56 0 57 0 58 0 59 0 60 0 61 0
		 62 0 63 0 64 0 65 0 66 0 67 0 68 0 69 0 70 0 71 0 72 0 73 0 74 0 75 0 76 0 77 0 78 0
		 79 0 80 0;
createNode animCurveTL -n "rear_right_spin_DRV_translateX";
	rename -uid "49DF0695-4438-0CEE-7A46-BA8B2BDAAD9D";
	setAttr ".tan" 18;
	setAttr ".wgt" no;
	setAttr -s 80 ".ktv[0:79]"  1 0 2 0 3 0 4 0 5 0 6 0 7 0 8 0 9 0 10 0
		 11 0 12 0 13 0 14 0 15 0 16 0 17 0 18 0 19 0 20 0 21 0 22 0 23 0 24 0 25 0 26 0 27 0
		 28 0 29 0 30 0 31 0 32 0 33 0 34 0 35 0 36 0 37 0 38 0 39 0 40 0 41 0 42 0 43 0 44 0
		 45 0 46 0 47 0 48 0 49 0 50 0 51 0 52 0 53 0 54 0 55 0 56 0 57 0 58 0 59 0 60 0 61 0
		 62 0 63 0 64 0 65 0 66 0 67 0 68 0 69 0 70 0 71 0 72 0 73 0 74 0 75 0 76 0 77 0 78 0
		 79 0 80 0;
createNode animCurveTL -n "rear_right_spin_DRV_translateY";
	rename -uid "0C9C5476-4C8A-0424-1E68-E79AF0402D05";
	setAttr ".tan" 18;
	setAttr ".wgt" no;
	setAttr -s 80 ".ktv[0:79]"  1 0 2 0 3 0 4 0 5 0 6 0 7 0 8 0 9 0 10 0
		 11 0 12 0 13 0 14 0 15 0 16 0 17 0 18 0 19 0 20 0 21 0 22 0 23 0 24 0 25 0 26 0 27 0
		 28 0 29 0 30 0 31 0 32 0 33 0 34 0 35 0 36 0 37 0 38 0 39 0 40 0 41 0 42 0 43 0 44 0
		 45 0 46 0 47 0 48 0 49 0 50 0 51 0 52 0 53 0 54 0 55 0 56 0 57 0 58 0 59 0 60 0 61 0
		 62 0 63 0 64 0 65 0 66 0 67 0 68 0 69 0 70 0 71 0 72 0 73 0 74 0 75 0 76 0 77 0 78 0
		 79 0 80 0;
createNode animCurveTL -n "rear_right_spin_DRV_translateZ";
	rename -uid "B8B27EBB-4A43-6C4F-A79C-DCB14BCF5956";
	setAttr ".tan" 18;
	setAttr ".wgt" no;
	setAttr -s 80 ".ktv[0:79]"  1 0 2 0 3 0 4 0 5 0 6 0 7 0 8 0 9 0 10 0
		 11 0 12 0 13 0 14 0 15 0 16 0 17 0 18 0 19 0 20 0 21 0 22 0 23 0 24 0 25 0 26 0 27 0
		 28 0 29 0 30 0 31 0 32 0 33 0 34 0 35 0 36 0 37 0 38 0 39 0 40 0 41 0 42 0 43 0 44 0
		 45 0 46 0 47 0 48 0 49 0 50 0 51 0 52 0 53 0 54 0 55 0 56 0 57 0 58 0 59 0 60 0 61 0
		 62 0 63 0 64 0 65 0 66 0 67 0 68 0 69 0 70 0 71 0 72 0 73 0 74 0 75 0 76 0 77 0 78 0
		 79 0 80 0;
createNode animCurveTA -n "rear_right_spin_DRV_rotateX";
	rename -uid "D33CDC15-42F1-7A92-0A03-0884ABAFB612";
	setAttr ".tan" 18;
	setAttr ".wgt" no;
	setAttr -s 80 ".ktv[0:79]"  1 0 2 0.66231423389471644 3 2.6146323164005261
		 4 5.7988994145538015 5 10.16936641705399 6 15.672457349052905 7 22.256305651410383
		 8 29.86904591634886 9 38.458984289136126 10 47.9622815525058 11 58.338840297788444
		 12 69.53590451054967 13 81.497470838837785 14 94.173981506580816 15 107.51525252145609
		 16 121.47103513906384 17 135.9915444108442 18 151.02298793027174 19 166.5282991783136
		 20 182.43401727523377 21 198.72572039116827 22 215.32134812911002 23 232.18352810664885
		 24 249.25754228422144 25 266.48794872408854 26 283.82578652000598 27 301.20893759459273
		 28 318.58891757907037 29 335.90342760519167 30 353.10138637534163 31 370.12507587720717
		 32 386.91998597646131 33 403.4358986488412 34 419.61440387933044 35 435.41405009281078
		 36 450.77220447025798 37 465.65360844304263 38 479.99514755163511 39 493.75854933614869
		 40 506.889342965629 41 519.98914145032506 42 533.65778472802867 43 547.86095665326445
		 44 562.54010943482967 45 577.66471799541955 46 593.1796701032481 47 609.04616416411807
		 48 625.2164237927318 49 641.64027194707467 50 658.2761261233984 51 675.06527697801869
		 52 691.96795803602731 53 708.92401633622205 54 725.88843836882597 55 742.81375538275688
		 56 759.63153729492331 57 776.32090534346924 58 792.79689667287994 59 809.05111133922776
		 60 825.00354158286211 61 840.63276420218381 62 855.88039695582268 63 870.70406553962607
		 64 885.06664346688137 65 898.90881902911929 66 912.19861167179226 67 924.88640309086156
		 68 936.92937181930165 69 948.27787304323738 70 958.88462362472183 71 968.71383661759216
		 72 977.7073133055211 73 985.81820106215332 74 992.996093425754 75 999.21116211987487
		 76 1004.401449408491 77 1008.5200274600078 78 1011.5199698894708 79 1013.3543488652851
		 80 1013.9762365558562;
createNode animCurveTA -n "rear_right_spin_DRV_rotateY";
	rename -uid "93982314-4F39-C2F1-A792-FAA7AC951626";
	setAttr ".tan" 18;
	setAttr ".wgt" no;
	setAttr -s 80 ".ktv[0:79]"  1 0 2 0 3 0 4 0 5 0 6 0 7 0 8 0 9 0 10 0
		 11 0 12 0 13 0 14 0 15 0 16 0 17 0 18 0 19 0 20 0 21 0 22 0 23 0 24 0 25 0 26 0 27 0
		 28 0 29 0 30 0 31 0 32 0 33 0 34 0 35 0 36 0 37 0 38 0 39 0 40 0 41 0 42 0 43 0 44 0
		 45 0 46 0 47 0 48 0 49 0 50 0 51 0 52 0 53 0 54 0 55 0 56 0 57 0 58 0 59 0 60 0 61 0
		 62 0 63 0 64 0 65 0 66 0 67 0 68 0 69 0 70 0 71 0 72 0 73 0 74 0 75 0 76 0 77 0 78 0
		 79 0 80 0;
createNode animCurveTA -n "rear_right_spin_DRV_rotateZ";
	rename -uid "0B1636A3-45CC-1F43-1459-30B8F3D60FA8";
	setAttr ".tan" 18;
	setAttr ".wgt" no;
	setAttr -s 80 ".ktv[0:79]"  1 0 2 0 3 0 4 0 5 0 6 0 7 0 8 0 9 0 10 0
		 11 0 12 0 13 0 14 0 15 0 16 0 17 0 18 0 19 0 20 0 21 0 22 0 23 0 24 0 25 0 26 0 27 0
		 28 0 29 0 30 0 31 0 32 0 33 0 34 0 35 0 36 0 37 0 38 0 39 0 40 0 41 0 42 0 43 0 44 0
		 45 0 46 0 47 0 48 0 49 0 50 0 51 0 52 0 53 0 54 0 55 0 56 0 57 0 58 0 59 0 60 0 61 0
		 62 0 63 0 64 0 65 0 66 0 67 0 68 0 69 0 70 0 71 0 72 0 73 0 74 0 75 0 76 0 77 0 78 0
		 79 0 80 0;
select -ne :time1;
	setAttr ".o" 1;
	setAttr ".unw" 1;
select -ne :hardwareRenderingGlobals;
	setAttr ".otfna" -type "stringArray" 22 "NURBS Curves" "NURBS Surfaces" "Polygons" "Subdiv Surface" "Particles" "Particle Instance" "Fluids" "Strokes" "Image Planes" "UI" "Lights" "Cameras" "Locators" "Joints" "IK Handles" "Deformers" "Motion Trails" "Components" "Hair Systems" "Follicles" "Misc. UI" "Ornaments"  ;
	setAttr ".otfva" -type "Int32Array" 22 0 1 1 1 1 1
		 1 1 1 0 0 0 0 0 0 0 0 0
		 0 0 0 0 ;
	setAttr ".fprt" yes;
select -ne :renderPartition;
	setAttr -s 2 ".st";
select -ne :renderGlobalsList1;
select -ne :defaultShaderList1;
	setAttr -s 5 ".s";
select -ne :postProcessList1;
	setAttr -s 2 ".p";
select -ne :defaultRenderingList1;
select -ne :initialShadingGroup;
	setAttr -s 6 ".dsm";
	setAttr ".ro" yes;
select -ne :initialParticleSE;
	setAttr ".ro" yes;
select -ne :defaultRenderGlobals;
	addAttr -ci true -h true -sn "dss" -ln "defaultSurfaceShader" -dt "string";
	setAttr ".dss" -type "string" "lambert1";
select -ne :defaultResolution;
	setAttr ".pa" 1;
select -ne :defaultColorMgtGlobals;
	setAttr ".cfe" yes;
	setAttr ".cfp" -type "string" "<MAYA_RESOURCES>/OCIO-configs/Maya2022-default/config.ocio";
	setAttr ".vtn" -type "string" "ACES 1.0 SDR-video (sRGB)";
	setAttr ".vn" -type "string" "ACES 1.0 SDR-video";
	setAttr ".dn" -type "string" "sRGB";
	setAttr ".wsn" -type "string" "ACEScg";
	setAttr ".otn" -type "string" "ACES 1.0 SDR-video (sRGB)";
	setAttr ".potn" -type "string" "ACES 1.0 SDR-video (sRGB)";
select -ne :hardwareRenderGlobals;
	setAttr ".ctrs" 256;
	setAttr ".btrs" 512;
connectAttr "vehicle_root_parentConstraint.ctx" "vehicle_root_JNT.tx";
connectAttr "vehicle_root_parentConstraint.cty" "vehicle_root_JNT.ty";
connectAttr "vehicle_root_parentConstraint.ctz" "vehicle_root_JNT.tz";
connectAttr "vehicle_root_parentConstraint.crx" "vehicle_root_JNT.rx";
connectAttr "vehicle_root_parentConstraint.cry" "vehicle_root_JNT.ry";
connectAttr "vehicle_root_parentConstraint.crz" "vehicle_root_JNT.rz";
connectAttr "vehicle_root_JNT.s" "vehicle_chassis_JNT.is";
connectAttr "vehicle_chassis_parentConstraint.ctx" "vehicle_chassis_JNT.tx";
connectAttr "vehicle_chassis_parentConstraint.cty" "vehicle_chassis_JNT.ty";
connectAttr "vehicle_chassis_parentConstraint.ctz" "vehicle_chassis_JNT.tz";
connectAttr "vehicle_chassis_parentConstraint.crx" "vehicle_chassis_JNT.rx";
connectAttr "vehicle_chassis_parentConstraint.cry" "vehicle_chassis_JNT.ry";
connectAttr "vehicle_chassis_parentConstraint.crz" "vehicle_chassis_JNT.rz";
connectAttr "vehicle_chassis_JNT.s" "front_left_mount_JNT.is";
connectAttr "front_left_mount_JNT.s" "front_left_wheel_JNT.is";
connectAttr "front_left_wheel_parentConstraint.ctx" "front_left_wheel_JNT.tx";
connectAttr "front_left_wheel_parentConstraint.cty" "front_left_wheel_JNT.ty";
connectAttr "front_left_wheel_parentConstraint.ctz" "front_left_wheel_JNT.tz";
connectAttr "front_left_wheel_parentConstraint.crx" "front_left_wheel_JNT.rx";
connectAttr "front_left_wheel_parentConstraint.cry" "front_left_wheel_JNT.ry";
connectAttr "front_left_wheel_parentConstraint.crz" "front_left_wheel_JNT.rz";
connectAttr "front_left_wheel_JNT.s" "front_left_contact_JNT.is";
connectAttr "front_left_wheel_JNT.ro" "front_left_wheel_parentConstraint.cro";
connectAttr "front_left_wheel_JNT.pim" "front_left_wheel_parentConstraint.cpim";
connectAttr "front_left_wheel_JNT.rp" "front_left_wheel_parentConstraint.crp";
connectAttr "front_left_wheel_JNT.rpt" "front_left_wheel_parentConstraint.crt";
connectAttr "front_left_wheel_JNT.jo" "front_left_wheel_parentConstraint.cjo";
connectAttr "front_left_wheel_CTRL.t" "front_left_wheel_parentConstraint.tg[0].tt"
		;
connectAttr "front_left_wheel_CTRL.rp" "front_left_wheel_parentConstraint.tg[0].trp"
		;
connectAttr "front_left_wheel_CTRL.rpt" "front_left_wheel_parentConstraint.tg[0].trt"
		;
connectAttr "front_left_wheel_CTRL.r" "front_left_wheel_parentConstraint.tg[0].tr"
		;
connectAttr "front_left_wheel_CTRL.ro" "front_left_wheel_parentConstraint.tg[0].tro"
		;
connectAttr "front_left_wheel_CTRL.s" "front_left_wheel_parentConstraint.tg[0].ts"
		;
connectAttr "front_left_wheel_CTRL.pm" "front_left_wheel_parentConstraint.tg[0].tpm"
		;
connectAttr "front_left_wheel_parentConstraint.w0" "front_left_wheel_parentConstraint.tg[0].tw"
		;
connectAttr "vehicle_chassis_JNT.s" "front_right_mount_JNT.is";
connectAttr "front_right_mount_JNT.s" "front_right_wheel_JNT.is";
connectAttr "front_right_wheel_parentConstraint.ctx" "front_right_wheel_JNT.tx";
connectAttr "front_right_wheel_parentConstraint.cty" "front_right_wheel_JNT.ty";
connectAttr "front_right_wheel_parentConstraint.ctz" "front_right_wheel_JNT.tz";
connectAttr "front_right_wheel_parentConstraint.crx" "front_right_wheel_JNT.rx";
connectAttr "front_right_wheel_parentConstraint.cry" "front_right_wheel_JNT.ry";
connectAttr "front_right_wheel_parentConstraint.crz" "front_right_wheel_JNT.rz";
connectAttr "front_right_wheel_JNT.s" "front_right_contact_JNT.is";
connectAttr "front_right_wheel_JNT.ro" "front_right_wheel_parentConstraint.cro";
connectAttr "front_right_wheel_JNT.pim" "front_right_wheel_parentConstraint.cpim"
		;
connectAttr "front_right_wheel_JNT.rp" "front_right_wheel_parentConstraint.crp";
connectAttr "front_right_wheel_JNT.rpt" "front_right_wheel_parentConstraint.crt"
		;
connectAttr "front_right_wheel_JNT.jo" "front_right_wheel_parentConstraint.cjo";
connectAttr "front_right_wheel_CTRL.t" "front_right_wheel_parentConstraint.tg[0].tt"
		;
connectAttr "front_right_wheel_CTRL.rp" "front_right_wheel_parentConstraint.tg[0].trp"
		;
connectAttr "front_right_wheel_CTRL.rpt" "front_right_wheel_parentConstraint.tg[0].trt"
		;
connectAttr "front_right_wheel_CTRL.r" "front_right_wheel_parentConstraint.tg[0].tr"
		;
connectAttr "front_right_wheel_CTRL.ro" "front_right_wheel_parentConstraint.tg[0].tro"
		;
connectAttr "front_right_wheel_CTRL.s" "front_right_wheel_parentConstraint.tg[0].ts"
		;
connectAttr "front_right_wheel_CTRL.pm" "front_right_wheel_parentConstraint.tg[0].tpm"
		;
connectAttr "front_right_wheel_parentConstraint.w0" "front_right_wheel_parentConstraint.tg[0].tw"
		;
connectAttr "vehicle_chassis_JNT.s" "rear_left_mount_JNT.is";
connectAttr "rear_left_mount_JNT.s" "rear_left_wheel_JNT.is";
connectAttr "rear_left_wheel_parentConstraint.ctx" "rear_left_wheel_JNT.tx";
connectAttr "rear_left_wheel_parentConstraint.cty" "rear_left_wheel_JNT.ty";
connectAttr "rear_left_wheel_parentConstraint.ctz" "rear_left_wheel_JNT.tz";
connectAttr "rear_left_wheel_parentConstraint.crx" "rear_left_wheel_JNT.rx";
connectAttr "rear_left_wheel_parentConstraint.cry" "rear_left_wheel_JNT.ry";
connectAttr "rear_left_wheel_parentConstraint.crz" "rear_left_wheel_JNT.rz";
connectAttr "rear_left_wheel_JNT.s" "rear_left_contact_JNT.is";
connectAttr "rear_left_wheel_JNT.ro" "rear_left_wheel_parentConstraint.cro";
connectAttr "rear_left_wheel_JNT.pim" "rear_left_wheel_parentConstraint.cpim";
connectAttr "rear_left_wheel_JNT.rp" "rear_left_wheel_parentConstraint.crp";
connectAttr "rear_left_wheel_JNT.rpt" "rear_left_wheel_parentConstraint.crt";
connectAttr "rear_left_wheel_JNT.jo" "rear_left_wheel_parentConstraint.cjo";
connectAttr "rear_left_wheel_CTRL.t" "rear_left_wheel_parentConstraint.tg[0].tt"
		;
connectAttr "rear_left_wheel_CTRL.rp" "rear_left_wheel_parentConstraint.tg[0].trp"
		;
connectAttr "rear_left_wheel_CTRL.rpt" "rear_left_wheel_parentConstraint.tg[0].trt"
		;
connectAttr "rear_left_wheel_CTRL.r" "rear_left_wheel_parentConstraint.tg[0].tr"
		;
connectAttr "rear_left_wheel_CTRL.ro" "rear_left_wheel_parentConstraint.tg[0].tro"
		;
connectAttr "rear_left_wheel_CTRL.s" "rear_left_wheel_parentConstraint.tg[0].ts"
		;
connectAttr "rear_left_wheel_CTRL.pm" "rear_left_wheel_parentConstraint.tg[0].tpm"
		;
connectAttr "rear_left_wheel_parentConstraint.w0" "rear_left_wheel_parentConstraint.tg[0].tw"
		;
connectAttr "vehicle_chassis_JNT.s" "rear_right_mount_JNT.is";
connectAttr "rear_right_mount_JNT.s" "rear_right_wheel_JNT.is";
connectAttr "rear_right_wheel_parentConstraint.ctx" "rear_right_wheel_JNT.tx";
connectAttr "rear_right_wheel_parentConstraint.cty" "rear_right_wheel_JNT.ty";
connectAttr "rear_right_wheel_parentConstraint.ctz" "rear_right_wheel_JNT.tz";
connectAttr "rear_right_wheel_parentConstraint.crx" "rear_right_wheel_JNT.rx";
connectAttr "rear_right_wheel_parentConstraint.cry" "rear_right_wheel_JNT.ry";
connectAttr "rear_right_wheel_parentConstraint.crz" "rear_right_wheel_JNT.rz";
connectAttr "rear_right_wheel_JNT.s" "rear_right_contact_JNT.is";
connectAttr "rear_right_wheel_JNT.ro" "rear_right_wheel_parentConstraint.cro";
connectAttr "rear_right_wheel_JNT.pim" "rear_right_wheel_parentConstraint.cpim";
connectAttr "rear_right_wheel_JNT.rp" "rear_right_wheel_parentConstraint.crp";
connectAttr "rear_right_wheel_JNT.rpt" "rear_right_wheel_parentConstraint.crt";
connectAttr "rear_right_wheel_JNT.jo" "rear_right_wheel_parentConstraint.cjo";
connectAttr "rear_right_wheel_CTRL.t" "rear_right_wheel_parentConstraint.tg[0].tt"
		;
connectAttr "rear_right_wheel_CTRL.rp" "rear_right_wheel_parentConstraint.tg[0].trp"
		;
connectAttr "rear_right_wheel_CTRL.rpt" "rear_right_wheel_parentConstraint.tg[0].trt"
		;
connectAttr "rear_right_wheel_CTRL.r" "rear_right_wheel_parentConstraint.tg[0].tr"
		;
connectAttr "rear_right_wheel_CTRL.ro" "rear_right_wheel_parentConstraint.tg[0].tro"
		;
connectAttr "rear_right_wheel_CTRL.s" "rear_right_wheel_parentConstraint.tg[0].ts"
		;
connectAttr "rear_right_wheel_CTRL.pm" "rear_right_wheel_parentConstraint.tg[0].tpm"
		;
connectAttr "rear_right_wheel_parentConstraint.w0" "rear_right_wheel_parentConstraint.tg[0].tw"
		;
connectAttr "vehicle_chassis_JNT.ro" "vehicle_chassis_parentConstraint.cro";
connectAttr "vehicle_chassis_JNT.pim" "vehicle_chassis_parentConstraint.cpim";
connectAttr "vehicle_chassis_JNT.rp" "vehicle_chassis_parentConstraint.crp";
connectAttr "vehicle_chassis_JNT.rpt" "vehicle_chassis_parentConstraint.crt";
connectAttr "vehicle_chassis_JNT.jo" "vehicle_chassis_parentConstraint.cjo";
connectAttr "vehicle_chassis_CTRL.t" "vehicle_chassis_parentConstraint.tg[0].tt"
		;
connectAttr "vehicle_chassis_CTRL.rp" "vehicle_chassis_parentConstraint.tg[0].trp"
		;
connectAttr "vehicle_chassis_CTRL.rpt" "vehicle_chassis_parentConstraint.tg[0].trt"
		;
connectAttr "vehicle_chassis_CTRL.r" "vehicle_chassis_parentConstraint.tg[0].tr"
		;
connectAttr "vehicle_chassis_CTRL.ro" "vehicle_chassis_parentConstraint.tg[0].tro"
		;
connectAttr "vehicle_chassis_CTRL.s" "vehicle_chassis_parentConstraint.tg[0].ts"
		;
connectAttr "vehicle_chassis_CTRL.pm" "vehicle_chassis_parentConstraint.tg[0].tpm"
		;
connectAttr "vehicle_chassis_parentConstraint.w0" "vehicle_chassis_parentConstraint.tg[0].tw"
		;
connectAttr "vehicle_root_JNT.ro" "vehicle_root_parentConstraint.cro";
connectAttr "vehicle_root_JNT.pim" "vehicle_root_parentConstraint.cpim";
connectAttr "vehicle_root_JNT.rp" "vehicle_root_parentConstraint.crp";
connectAttr "vehicle_root_JNT.rpt" "vehicle_root_parentConstraint.crt";
connectAttr "vehicle_root_JNT.jo" "vehicle_root_parentConstraint.cjo";
connectAttr "vehicle_global_CTRL.t" "vehicle_root_parentConstraint.tg[0].tt";
connectAttr "vehicle_global_CTRL.rp" "vehicle_root_parentConstraint.tg[0].trp";
connectAttr "vehicle_global_CTRL.rpt" "vehicle_root_parentConstraint.tg[0].trt";
connectAttr "vehicle_global_CTRL.r" "vehicle_root_parentConstraint.tg[0].tr";
connectAttr "vehicle_global_CTRL.ro" "vehicle_root_parentConstraint.tg[0].tro";
connectAttr "vehicle_global_CTRL.s" "vehicle_root_parentConstraint.tg[0].ts";
connectAttr "vehicle_global_CTRL.pm" "vehicle_root_parentConstraint.tg[0].tpm";
connectAttr "vehicle_root_parentConstraint.w0" "vehicle_root_parentConstraint.tg[0].tw"
		;
connectAttr "vehicle_global_CTRL_translateX.o" "vehicle_global_CTRL.tx";
connectAttr "vehicle_global_CTRL_translateZ.o" "vehicle_global_CTRL.tz";
connectAttr "vehicle_global_CTRL_rotateY.o" "vehicle_global_CTRL.ry";
connectAttr "vehicle_chassis_CTRL_steering.o" "vehicle_chassis_CTRL.steering";
connectAttr "front_left_suspension_DRV_translateX.o" "front_left_suspension_DRV.tx"
		;
connectAttr "front_left_suspension_DRV_translateY.o" "front_left_suspension_DRV.ty"
		;
connectAttr "front_left_suspension_DRV_translateZ.o" "front_left_suspension_DRV.tz"
		;
connectAttr "front_left_suspension_DRV_rotateX.o" "front_left_suspension_DRV.rx"
		;
connectAttr "front_left_suspension_DRV_rotateY.o" "front_left_suspension_DRV.ry"
		;
connectAttr "front_left_suspension_DRV_rotateZ.o" "front_left_suspension_DRV.rz"
		;
connectAttr "front_left_steer_DRV_translateX.o" "front_left_steer_DRV.tx";
connectAttr "front_left_steer_DRV_translateY.o" "front_left_steer_DRV.ty";
connectAttr "front_left_steer_DRV_translateZ.o" "front_left_steer_DRV.tz";
connectAttr "front_left_steer_DRV_rotateX.o" "front_left_steer_DRV.rx";
connectAttr "front_left_steer_DRV_rotateY.o" "front_left_steer_DRV.ry";
connectAttr "front_left_steer_DRV_rotateZ.o" "front_left_steer_DRV.rz";
connectAttr "front_left_spin_DRV_translateX.o" "front_left_spin_DRV.tx";
connectAttr "front_left_spin_DRV_translateY.o" "front_left_spin_DRV.ty";
connectAttr "front_left_spin_DRV_translateZ.o" "front_left_spin_DRV.tz";
connectAttr "front_left_spin_DRV_rotateX.o" "front_left_spin_DRV.rx";
connectAttr "front_left_spin_DRV_rotateY.o" "front_left_spin_DRV.ry";
connectAttr "front_left_spin_DRV_rotateZ.o" "front_left_spin_DRV.rz";
connectAttr "front_right_suspension_DRV_translateX.o" "front_right_suspension_DRV.tx"
		;
connectAttr "front_right_suspension_DRV_translateY.o" "front_right_suspension_DRV.ty"
		;
connectAttr "front_right_suspension_DRV_translateZ.o" "front_right_suspension_DRV.tz"
		;
connectAttr "front_right_suspension_DRV_rotateX.o" "front_right_suspension_DRV.rx"
		;
connectAttr "front_right_suspension_DRV_rotateY.o" "front_right_suspension_DRV.ry"
		;
connectAttr "front_right_suspension_DRV_rotateZ.o" "front_right_suspension_DRV.rz"
		;
connectAttr "front_right_steer_DRV_translateX.o" "front_right_steer_DRV.tx";
connectAttr "front_right_steer_DRV_translateY.o" "front_right_steer_DRV.ty";
connectAttr "front_right_steer_DRV_translateZ.o" "front_right_steer_DRV.tz";
connectAttr "front_right_steer_DRV_rotateX.o" "front_right_steer_DRV.rx";
connectAttr "front_right_steer_DRV_rotateY.o" "front_right_steer_DRV.ry";
connectAttr "front_right_steer_DRV_rotateZ.o" "front_right_steer_DRV.rz";
connectAttr "front_right_spin_DRV_translateX.o" "front_right_spin_DRV.tx";
connectAttr "front_right_spin_DRV_translateY.o" "front_right_spin_DRV.ty";
connectAttr "front_right_spin_DRV_translateZ.o" "front_right_spin_DRV.tz";
connectAttr "front_right_spin_DRV_rotateX.o" "front_right_spin_DRV.rx";
connectAttr "front_right_spin_DRV_rotateY.o" "front_right_spin_DRV.ry";
connectAttr "front_right_spin_DRV_rotateZ.o" "front_right_spin_DRV.rz";
connectAttr "rear_left_suspension_DRV_translateX.o" "rear_left_suspension_DRV.tx"
		;
connectAttr "rear_left_suspension_DRV_translateY.o" "rear_left_suspension_DRV.ty"
		;
connectAttr "rear_left_suspension_DRV_translateZ.o" "rear_left_suspension_DRV.tz"
		;
connectAttr "rear_left_suspension_DRV_rotateX.o" "rear_left_suspension_DRV.rx";
connectAttr "rear_left_suspension_DRV_rotateY.o" "rear_left_suspension_DRV.ry";
connectAttr "rear_left_suspension_DRV_rotateZ.o" "rear_left_suspension_DRV.rz";
connectAttr "rear_left_steer_DRV_translateX.o" "rear_left_steer_DRV.tx";
connectAttr "rear_left_steer_DRV_translateY.o" "rear_left_steer_DRV.ty";
connectAttr "rear_left_steer_DRV_translateZ.o" "rear_left_steer_DRV.tz";
connectAttr "rear_left_steer_DRV_rotateX.o" "rear_left_steer_DRV.rx";
connectAttr "rear_left_steer_DRV_rotateY.o" "rear_left_steer_DRV.ry";
connectAttr "rear_left_steer_DRV_rotateZ.o" "rear_left_steer_DRV.rz";
connectAttr "rear_left_spin_DRV_translateX.o" "rear_left_spin_DRV.tx";
connectAttr "rear_left_spin_DRV_translateY.o" "rear_left_spin_DRV.ty";
connectAttr "rear_left_spin_DRV_translateZ.o" "rear_left_spin_DRV.tz";
connectAttr "rear_left_spin_DRV_rotateX.o" "rear_left_spin_DRV.rx";
connectAttr "rear_left_spin_DRV_rotateY.o" "rear_left_spin_DRV.ry";
connectAttr "rear_left_spin_DRV_rotateZ.o" "rear_left_spin_DRV.rz";
connectAttr "rear_right_suspension_DRV_translateX.o" "rear_right_suspension_DRV.tx"
		;
connectAttr "rear_right_suspension_DRV_translateY.o" "rear_right_suspension_DRV.ty"
		;
connectAttr "rear_right_suspension_DRV_translateZ.o" "rear_right_suspension_DRV.tz"
		;
connectAttr "rear_right_suspension_DRV_rotateX.o" "rear_right_suspension_DRV.rx"
		;
connectAttr "rear_right_suspension_DRV_rotateY.o" "rear_right_suspension_DRV.ry"
		;
connectAttr "rear_right_suspension_DRV_rotateZ.o" "rear_right_suspension_DRV.rz"
		;
connectAttr "rear_right_steer_DRV_translateX.o" "rear_right_steer_DRV.tx";
connectAttr "rear_right_steer_DRV_translateY.o" "rear_right_steer_DRV.ty";
connectAttr "rear_right_steer_DRV_translateZ.o" "rear_right_steer_DRV.tz";
connectAttr "rear_right_steer_DRV_rotateX.o" "rear_right_steer_DRV.rx";
connectAttr "rear_right_steer_DRV_rotateY.o" "rear_right_steer_DRV.ry";
connectAttr "rear_right_steer_DRV_rotateZ.o" "rear_right_steer_DRV.rz";
connectAttr "rear_right_spin_DRV_translateX.o" "rear_right_spin_DRV.tx";
connectAttr "rear_right_spin_DRV_translateY.o" "rear_right_spin_DRV.ty";
connectAttr "rear_right_spin_DRV_translateZ.o" "rear_right_spin_DRV.tz";
connectAttr "rear_right_spin_DRV_rotateX.o" "rear_right_spin_DRV.rx";
connectAttr "rear_right_spin_DRV_rotateY.o" "rear_right_spin_DRV.ry";
connectAttr "rear_right_spin_DRV_rotateZ.o" "rear_right_spin_DRV.rz";
connectAttr "vehicle_RIG.debugGroundRays" "vehicle_ground_debug_GRP.v";
connectAttr "front_left_preview_GEO_parentConstraint1.ctx" "front_left_preview_GEO.tx"
		;
connectAttr "front_left_preview_GEO_parentConstraint1.cty" "front_left_preview_GEO.ty"
		;
connectAttr "front_left_preview_GEO_parentConstraint1.ctz" "front_left_preview_GEO.tz"
		;
connectAttr "front_left_preview_GEO_parentConstraint1.crx" "front_left_preview_GEO.rx"
		;
connectAttr "front_left_preview_GEO_parentConstraint1.cry" "front_left_preview_GEO.ry"
		;
connectAttr "front_left_preview_GEO_parentConstraint1.crz" "front_left_preview_GEO.rz"
		;
connectAttr "polyCylinder1.out" "front_left_preview_GEOShape.i";
connectAttr "front_left_preview_GEO.ro" "front_left_preview_GEO_parentConstraint1.cro"
		;
connectAttr "front_left_preview_GEO.pim" "front_left_preview_GEO_parentConstraint1.cpim"
		;
connectAttr "front_left_preview_GEO.rp" "front_left_preview_GEO_parentConstraint1.crp"
		;
connectAttr "front_left_preview_GEO.rpt" "front_left_preview_GEO_parentConstraint1.crt"
		;
connectAttr "front_left_wheel_JNT.t" "front_left_preview_GEO_parentConstraint1.tg[0].tt"
		;
connectAttr "front_left_wheel_JNT.rp" "front_left_preview_GEO_parentConstraint1.tg[0].trp"
		;
connectAttr "front_left_wheel_JNT.rpt" "front_left_preview_GEO_parentConstraint1.tg[0].trt"
		;
connectAttr "front_left_wheel_JNT.r" "front_left_preview_GEO_parentConstraint1.tg[0].tr"
		;
connectAttr "front_left_wheel_JNT.ro" "front_left_preview_GEO_parentConstraint1.tg[0].tro"
		;
connectAttr "front_left_wheel_JNT.s" "front_left_preview_GEO_parentConstraint1.tg[0].ts"
		;
connectAttr "front_left_wheel_JNT.pm" "front_left_preview_GEO_parentConstraint1.tg[0].tpm"
		;
connectAttr "front_left_wheel_JNT.jo" "front_left_preview_GEO_parentConstraint1.tg[0].tjo"
		;
connectAttr "front_left_wheel_JNT.ssc" "front_left_preview_GEO_parentConstraint1.tg[0].tsc"
		;
connectAttr "front_left_wheel_JNT.is" "front_left_preview_GEO_parentConstraint1.tg[0].tis"
		;
connectAttr "front_left_preview_GEO_parentConstraint1.w0" "front_left_preview_GEO_parentConstraint1.tg[0].tw"
		;
connectAttr "front_right_preview_GEO_parentConstraint1.ctx" "front_right_preview_GEO.tx"
		;
connectAttr "front_right_preview_GEO_parentConstraint1.cty" "front_right_preview_GEO.ty"
		;
connectAttr "front_right_preview_GEO_parentConstraint1.ctz" "front_right_preview_GEO.tz"
		;
connectAttr "front_right_preview_GEO_parentConstraint1.crx" "front_right_preview_GEO.rx"
		;
connectAttr "front_right_preview_GEO_parentConstraint1.cry" "front_right_preview_GEO.ry"
		;
connectAttr "front_right_preview_GEO_parentConstraint1.crz" "front_right_preview_GEO.rz"
		;
connectAttr "polyCylinder2.out" "front_right_preview_GEOShape.i";
connectAttr "front_right_preview_GEO.ro" "front_right_preview_GEO_parentConstraint1.cro"
		;
connectAttr "front_right_preview_GEO.pim" "front_right_preview_GEO_parentConstraint1.cpim"
		;
connectAttr "front_right_preview_GEO.rp" "front_right_preview_GEO_parentConstraint1.crp"
		;
connectAttr "front_right_preview_GEO.rpt" "front_right_preview_GEO_parentConstraint1.crt"
		;
connectAttr "front_right_wheel_JNT.t" "front_right_preview_GEO_parentConstraint1.tg[0].tt"
		;
connectAttr "front_right_wheel_JNT.rp" "front_right_preview_GEO_parentConstraint1.tg[0].trp"
		;
connectAttr "front_right_wheel_JNT.rpt" "front_right_preview_GEO_parentConstraint1.tg[0].trt"
		;
connectAttr "front_right_wheel_JNT.r" "front_right_preview_GEO_parentConstraint1.tg[0].tr"
		;
connectAttr "front_right_wheel_JNT.ro" "front_right_preview_GEO_parentConstraint1.tg[0].tro"
		;
connectAttr "front_right_wheel_JNT.s" "front_right_preview_GEO_parentConstraint1.tg[0].ts"
		;
connectAttr "front_right_wheel_JNT.pm" "front_right_preview_GEO_parentConstraint1.tg[0].tpm"
		;
connectAttr "front_right_wheel_JNT.jo" "front_right_preview_GEO_parentConstraint1.tg[0].tjo"
		;
connectAttr "front_right_wheel_JNT.ssc" "front_right_preview_GEO_parentConstraint1.tg[0].tsc"
		;
connectAttr "front_right_wheel_JNT.is" "front_right_preview_GEO_parentConstraint1.tg[0].tis"
		;
connectAttr "front_right_preview_GEO_parentConstraint1.w0" "front_right_preview_GEO_parentConstraint1.tg[0].tw"
		;
connectAttr "rear_left_preview_GEO_parentConstraint1.ctx" "rear_left_preview_GEO.tx"
		;
connectAttr "rear_left_preview_GEO_parentConstraint1.cty" "rear_left_preview_GEO.ty"
		;
connectAttr "rear_left_preview_GEO_parentConstraint1.ctz" "rear_left_preview_GEO.tz"
		;
connectAttr "rear_left_preview_GEO_parentConstraint1.crx" "rear_left_preview_GEO.rx"
		;
connectAttr "rear_left_preview_GEO_parentConstraint1.cry" "rear_left_preview_GEO.ry"
		;
connectAttr "rear_left_preview_GEO_parentConstraint1.crz" "rear_left_preview_GEO.rz"
		;
connectAttr "polyCylinder3.out" "rear_left_preview_GEOShape.i";
connectAttr "rear_left_preview_GEO.ro" "rear_left_preview_GEO_parentConstraint1.cro"
		;
connectAttr "rear_left_preview_GEO.pim" "rear_left_preview_GEO_parentConstraint1.cpim"
		;
connectAttr "rear_left_preview_GEO.rp" "rear_left_preview_GEO_parentConstraint1.crp"
		;
connectAttr "rear_left_preview_GEO.rpt" "rear_left_preview_GEO_parentConstraint1.crt"
		;
connectAttr "rear_left_wheel_JNT.t" "rear_left_preview_GEO_parentConstraint1.tg[0].tt"
		;
connectAttr "rear_left_wheel_JNT.rp" "rear_left_preview_GEO_parentConstraint1.tg[0].trp"
		;
connectAttr "rear_left_wheel_JNT.rpt" "rear_left_preview_GEO_parentConstraint1.tg[0].trt"
		;
connectAttr "rear_left_wheel_JNT.r" "rear_left_preview_GEO_parentConstraint1.tg[0].tr"
		;
connectAttr "rear_left_wheel_JNT.ro" "rear_left_preview_GEO_parentConstraint1.tg[0].tro"
		;
connectAttr "rear_left_wheel_JNT.s" "rear_left_preview_GEO_parentConstraint1.tg[0].ts"
		;
connectAttr "rear_left_wheel_JNT.pm" "rear_left_preview_GEO_parentConstraint1.tg[0].tpm"
		;
connectAttr "rear_left_wheel_JNT.jo" "rear_left_preview_GEO_parentConstraint1.tg[0].tjo"
		;
connectAttr "rear_left_wheel_JNT.ssc" "rear_left_preview_GEO_parentConstraint1.tg[0].tsc"
		;
connectAttr "rear_left_wheel_JNT.is" "rear_left_preview_GEO_parentConstraint1.tg[0].tis"
		;
connectAttr "rear_left_preview_GEO_parentConstraint1.w0" "rear_left_preview_GEO_parentConstraint1.tg[0].tw"
		;
connectAttr "rear_right_preview_GEO_parentConstraint1.ctx" "rear_right_preview_GEO.tx"
		;
connectAttr "rear_right_preview_GEO_parentConstraint1.cty" "rear_right_preview_GEO.ty"
		;
connectAttr "rear_right_preview_GEO_parentConstraint1.ctz" "rear_right_preview_GEO.tz"
		;
connectAttr "rear_right_preview_GEO_parentConstraint1.crx" "rear_right_preview_GEO.rx"
		;
connectAttr "rear_right_preview_GEO_parentConstraint1.cry" "rear_right_preview_GEO.ry"
		;
connectAttr "rear_right_preview_GEO_parentConstraint1.crz" "rear_right_preview_GEO.rz"
		;
connectAttr "polyCylinder4.out" "rear_right_preview_GEOShape.i";
connectAttr "rear_right_preview_GEO.ro" "rear_right_preview_GEO_parentConstraint1.cro"
		;
connectAttr "rear_right_preview_GEO.pim" "rear_right_preview_GEO_parentConstraint1.cpim"
		;
connectAttr "rear_right_preview_GEO.rp" "rear_right_preview_GEO_parentConstraint1.crp"
		;
connectAttr "rear_right_preview_GEO.rpt" "rear_right_preview_GEO_parentConstraint1.crt"
		;
connectAttr "rear_right_wheel_JNT.t" "rear_right_preview_GEO_parentConstraint1.tg[0].tt"
		;
connectAttr "rear_right_wheel_JNT.rp" "rear_right_preview_GEO_parentConstraint1.tg[0].trp"
		;
connectAttr "rear_right_wheel_JNT.rpt" "rear_right_preview_GEO_parentConstraint1.tg[0].trt"
		;
connectAttr "rear_right_wheel_JNT.r" "rear_right_preview_GEO_parentConstraint1.tg[0].tr"
		;
connectAttr "rear_right_wheel_JNT.ro" "rear_right_preview_GEO_parentConstraint1.tg[0].tro"
		;
connectAttr "rear_right_wheel_JNT.s" "rear_right_preview_GEO_parentConstraint1.tg[0].ts"
		;
connectAttr "rear_right_wheel_JNT.pm" "rear_right_preview_GEO_parentConstraint1.tg[0].tpm"
		;
connectAttr "rear_right_wheel_JNT.jo" "rear_right_preview_GEO_parentConstraint1.tg[0].tjo"
		;
connectAttr "rear_right_wheel_JNT.ssc" "rear_right_preview_GEO_parentConstraint1.tg[0].tsc"
		;
connectAttr "rear_right_wheel_JNT.is" "rear_right_preview_GEO_parentConstraint1.tg[0].tis"
		;
connectAttr "rear_right_preview_GEO_parentConstraint1.w0" "rear_right_preview_GEO_parentConstraint1.tg[0].tw"
		;
connectAttr "vehicle_chassis_preview_GEO_parentConstraint1.ctx" "vehicle_chassis_preview_GEO.tx"
		;
connectAttr "vehicle_chassis_preview_GEO_parentConstraint1.cty" "vehicle_chassis_preview_GEO.ty"
		;
connectAttr "vehicle_chassis_preview_GEO_parentConstraint1.ctz" "vehicle_chassis_preview_GEO.tz"
		;
connectAttr "vehicle_chassis_preview_GEO_parentConstraint1.crx" "vehicle_chassis_preview_GEO.rx"
		;
connectAttr "vehicle_chassis_preview_GEO_parentConstraint1.cry" "vehicle_chassis_preview_GEO.ry"
		;
connectAttr "vehicle_chassis_preview_GEO_parentConstraint1.crz" "vehicle_chassis_preview_GEO.rz"
		;
connectAttr "polyCube1.out" "vehicle_chassis_preview_GEOShape.i";
connectAttr "vehicle_chassis_preview_GEO.ro" "vehicle_chassis_preview_GEO_parentConstraint1.cro"
		;
connectAttr "vehicle_chassis_preview_GEO.pim" "vehicle_chassis_preview_GEO_parentConstraint1.cpim"
		;
connectAttr "vehicle_chassis_preview_GEO.rp" "vehicle_chassis_preview_GEO_parentConstraint1.crp"
		;
connectAttr "vehicle_chassis_preview_GEO.rpt" "vehicle_chassis_preview_GEO_parentConstraint1.crt"
		;
connectAttr "vehicle_chassis_JNT.t" "vehicle_chassis_preview_GEO_parentConstraint1.tg[0].tt"
		;
connectAttr "vehicle_chassis_JNT.rp" "vehicle_chassis_preview_GEO_parentConstraint1.tg[0].trp"
		;
connectAttr "vehicle_chassis_JNT.rpt" "vehicle_chassis_preview_GEO_parentConstraint1.tg[0].trt"
		;
connectAttr "vehicle_chassis_JNT.r" "vehicle_chassis_preview_GEO_parentConstraint1.tg[0].tr"
		;
connectAttr "vehicle_chassis_JNT.ro" "vehicle_chassis_preview_GEO_parentConstraint1.tg[0].tro"
		;
connectAttr "vehicle_chassis_JNT.s" "vehicle_chassis_preview_GEO_parentConstraint1.tg[0].ts"
		;
connectAttr "vehicle_chassis_JNT.pm" "vehicle_chassis_preview_GEO_parentConstraint1.tg[0].tpm"
		;
connectAttr "vehicle_chassis_JNT.jo" "vehicle_chassis_preview_GEO_parentConstraint1.tg[0].tjo"
		;
connectAttr "vehicle_chassis_JNT.ssc" "vehicle_chassis_preview_GEO_parentConstraint1.tg[0].tsc"
		;
connectAttr "vehicle_chassis_JNT.is" "vehicle_chassis_preview_GEO_parentConstraint1.tg[0].tis"
		;
connectAttr "vehicle_chassis_preview_GEO_parentConstraint1.w0" "vehicle_chassis_preview_GEO_parentConstraint1.tg[0].tw"
		;
connectAttr "polyPlane1.out" "vehicle_demo_ground_GEOShape.i";
relationship "link" ":lightLinker1" ":initialShadingGroup.message" ":defaultLightSet.message";
relationship "link" ":lightLinker1" ":initialParticleSE.message" ":defaultLightSet.message";
relationship "shadowLink" ":lightLinker1" ":initialShadingGroup.message" ":defaultLightSet.message";
relationship "shadowLink" ":lightLinker1" ":initialParticleSE.message" ":defaultLightSet.message";
connectAttr "layerManager.dli[0]" "defaultLayer.id";
connectAttr "renderLayerManager.rlmi[0]" "defaultRenderLayer.rlid";
connectAttr "defaultRenderLayer.msg" ":defaultRenderingList1.r" -na;
connectAttr "front_left_preview_GEOShape.iog" ":initialShadingGroup.dsm" -na;
connectAttr "front_right_preview_GEOShape.iog" ":initialShadingGroup.dsm" -na;
connectAttr "rear_left_preview_GEOShape.iog" ":initialShadingGroup.dsm" -na;
connectAttr "rear_right_preview_GEOShape.iog" ":initialShadingGroup.dsm" -na;
connectAttr "vehicle_chassis_preview_GEOShape.iog" ":initialShadingGroup.dsm" -na
		;
connectAttr "vehicle_demo_ground_GEOShape.iog" ":initialShadingGroup.dsm" -na;
// End of vehicle_rig_demo.ma
