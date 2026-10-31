//Maya ASCII 2023 scene
//Name: vehicle_rig.ma
//Last modified: Wed, Oct 14, 2026 02:49:10 PM
//Codeset: 1252
requires maya "2023";
currentUnit -l centimeter -a degree -t film;
fileInfo "application" "maya";
fileInfo "product" "Maya 2023";
fileInfo "version" "2023";
fileInfo "cutIdentifier" "202405151550-05a853e76d";
fileInfo "osv" "Windows 10 Home v2009 (Build: 19045)";
fileInfo "UUID" "69B8CF18-40D5-FAC9-B4E9-EE9AE47CF0D7";
createNode transform -s -n "persp";
	rename -uid "99E8618D-4728-4E2E-5B37-BEBCC66751C7";
	setAttr ".v" no;
	setAttr ".t" -type "double3" 28 21 28 ;
	setAttr ".r" -type "double3" -27.938352729602379 44.999999999999972 -5.172681101354183e-14 ;
createNode camera -s -n "perspShape" -p "persp";
	rename -uid "1DF16C74-42AA-07EF-9C82-7EA9222F1033";
	setAttr -k off ".v" no;
	setAttr ".fl" 34.999999999999993;
	setAttr ".coi" 44.82186966202994;
	setAttr ".imn" -type "string" "persp";
	setAttr ".den" -type "string" "persp_depth";
	setAttr ".man" -type "string" "persp_mask";
	setAttr ".hc" -type "string" "viewSet -p %camera";
createNode transform -s -n "top";
	rename -uid "358AB2D9-498F-2E95-AEE5-F0B5CCF4A9BE";
	setAttr ".v" no;
	setAttr ".t" -type "double3" 0 1000.1 0 ;
	setAttr ".r" -type "double3" -90 0 0 ;
createNode camera -s -n "topShape" -p "top";
	rename -uid "D03992D6-47BB-2F45-E1C2-D882B56714F1";
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
	rename -uid "B49053C3-498C-2F4A-DE2E-BFB51939248C";
	setAttr ".v" no;
	setAttr ".t" -type "double3" 0 0 1000.1 ;
createNode camera -s -n "frontShape" -p "front";
	rename -uid "197D436E-4B9D-03F9-13AC-0392D16F6AC3";
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
	rename -uid "2E1CEC6E-4C01-E3A8-B3A0-73B98FFA54BD";
	setAttr ".v" no;
	setAttr ".t" -type "double3" 1000.1 0 0 ;
	setAttr ".r" -type "double3" 0 90 0 ;
createNode camera -s -n "sideShape" -p "side";
	rename -uid "C8B21A6D-4407-710A-4FFD-20941F592BBC";
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
	rename -uid "6230B4C1-426A-7F64-7A54-8092E499B8B3";
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
	rename -uid "E3BD98E0-461C-E952-F8F6-1F84EF096271";
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
	rename -uid "87F45D1E-47F7-2441-3EB8-3E89092A1A52";
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
	rename -uid "890D194A-4D13-099F-1921-AEA6F3CF0C22";
	addAttr -ci true -sn "tcVehicleRole" -ln "tcVehicleRole" -dt "string";
	addAttr -ci true -sn "tcWheelId" -ln "tcWheelId" -dt "string";
	setAttr ".mnrl" -type "double3" -360 -360 -360 ;
	setAttr ".mxrl" -type "double3" 360 360 360 ;
	setAttr ".radi" 5;
	setAttr ".tcVehicleRole" -type "string" "wheel";
	setAttr ".tcWheelId" -type "string" "front_left";
createNode joint -n "front_left_contact_JNT" -p "front_left_wheel_JNT";
	rename -uid "E4B98541-4BB1-D803-C94C-80AD4E6CCE14";
	addAttr -ci true -sn "tcVehicleRole" -ln "tcVehicleRole" -dt "string";
	addAttr -ci true -sn "tcWheelId" -ln "tcWheelId" -dt "string";
	setAttr ".t" -type "double3" 0 -34.000000000000014 0 ;
	setAttr ".mnrl" -type "double3" -360 -360 -360 ;
	setAttr ".mxrl" -type "double3" 360 360 360 ;
	setAttr ".radi" 2;
	setAttr ".tcVehicleRole" -type "string" "ground_contact";
	setAttr ".tcWheelId" -type "string" "front_left";
createNode parentConstraint -n "front_left_wheel_parentConstraint" -p "front_left_wheel_JNT";
	rename -uid "E78CC8F7-4AF8-A072-6C16-AA9C9AB9E34A";
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
	rename -uid "5A7CF18F-47B2-6395-11C3-B792F5C68ED7";
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
	rename -uid "26F44645-49C3-1D58-9131-3891DCC39B49";
	addAttr -ci true -sn "tcVehicleRole" -ln "tcVehicleRole" -dt "string";
	addAttr -ci true -sn "tcWheelId" -ln "tcWheelId" -dt "string";
	setAttr ".mnrl" -type "double3" -360 -360 -360 ;
	setAttr ".mxrl" -type "double3" 360 360 360 ;
	setAttr ".radi" 5;
	setAttr ".tcVehicleRole" -type "string" "wheel";
	setAttr ".tcWheelId" -type "string" "front_right";
createNode joint -n "front_right_contact_JNT" -p "front_right_wheel_JNT";
	rename -uid "141DE562-4E7A-86F9-0672-2298842BE4CC";
	addAttr -ci true -sn "tcVehicleRole" -ln "tcVehicleRole" -dt "string";
	addAttr -ci true -sn "tcWheelId" -ln "tcWheelId" -dt "string";
	setAttr ".t" -type "double3" 0 -34.000000000000014 0 ;
	setAttr ".mnrl" -type "double3" -360 -360 -360 ;
	setAttr ".mxrl" -type "double3" 360 360 360 ;
	setAttr ".radi" 2;
	setAttr ".tcVehicleRole" -type "string" "ground_contact";
	setAttr ".tcWheelId" -type "string" "front_right";
createNode parentConstraint -n "front_right_wheel_parentConstraint" -p "front_right_wheel_JNT";
	rename -uid "7E49FF39-4177-1B1B-E45E-9DA98B5C8AC9";
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
	rename -uid "33DADE86-43B0-FB2C-FC13-B6A481DEF6E7";
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
	rename -uid "EF5D1EF1-4D8D-3A50-E2CC-CC9FCEB97D7B";
	addAttr -ci true -sn "tcVehicleRole" -ln "tcVehicleRole" -dt "string";
	addAttr -ci true -sn "tcWheelId" -ln "tcWheelId" -dt "string";
	setAttr ".mnrl" -type "double3" -360 -360 -360 ;
	setAttr ".mxrl" -type "double3" 360 360 360 ;
	setAttr ".radi" 5;
	setAttr ".tcVehicleRole" -type "string" "wheel";
	setAttr ".tcWheelId" -type "string" "rear_left";
createNode joint -n "rear_left_contact_JNT" -p "rear_left_wheel_JNT";
	rename -uid "CB4363AA-4C0C-A88D-263A-7C83CECD45C0";
	addAttr -ci true -sn "tcVehicleRole" -ln "tcVehicleRole" -dt "string";
	addAttr -ci true -sn "tcWheelId" -ln "tcWheelId" -dt "string";
	setAttr ".t" -type "double3" 0 -34.000000000000014 0 ;
	setAttr ".mnrl" -type "double3" -360 -360 -360 ;
	setAttr ".mxrl" -type "double3" 360 360 360 ;
	setAttr ".radi" 2;
	setAttr ".tcVehicleRole" -type "string" "ground_contact";
	setAttr ".tcWheelId" -type "string" "rear_left";
createNode parentConstraint -n "rear_left_wheel_parentConstraint" -p "rear_left_wheel_JNT";
	rename -uid "76C8792D-44A3-4E4B-70FF-3C826B4E2191";
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
	rename -uid "5DF15C88-4F47-7CA4-2C87-20A9F74DEB2D";
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
	rename -uid "83421004-4E4B-8A3A-4FF8-619781909970";
	addAttr -ci true -sn "tcVehicleRole" -ln "tcVehicleRole" -dt "string";
	addAttr -ci true -sn "tcWheelId" -ln "tcWheelId" -dt "string";
	setAttr ".mnrl" -type "double3" -360 -360 -360 ;
	setAttr ".mxrl" -type "double3" 360 360 360 ;
	setAttr ".radi" 5;
	setAttr ".tcVehicleRole" -type "string" "wheel";
	setAttr ".tcWheelId" -type "string" "rear_right";
createNode joint -n "rear_right_contact_JNT" -p "rear_right_wheel_JNT";
	rename -uid "7AD9AC45-46F3-8BF5-AA10-4A8FE2FDBAE1";
	addAttr -ci true -sn "tcVehicleRole" -ln "tcVehicleRole" -dt "string";
	addAttr -ci true -sn "tcWheelId" -ln "tcWheelId" -dt "string";
	setAttr ".t" -type "double3" 0 -34.000000000000014 0 ;
	setAttr ".mnrl" -type "double3" -360 -360 -360 ;
	setAttr ".mxrl" -type "double3" 360 360 360 ;
	setAttr ".radi" 2;
	setAttr ".tcVehicleRole" -type "string" "ground_contact";
	setAttr ".tcWheelId" -type "string" "rear_right";
createNode parentConstraint -n "rear_right_wheel_parentConstraint" -p "rear_right_wheel_JNT";
	rename -uid "C04DEC14-4BA3-A750-01D8-1C831EECDA33";
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
	rename -uid "714AB7E1-42E9-E47D-A918-BCACE678C3CD";
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
	rename -uid "8006E0D5-4227-6265-9DFA-39AE4AE6EE5A";
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
	rename -uid "7E4C1DFB-4355-8F83-3242-F6B09CC5C04F";
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
	setAttr ".tcGroundMeshes" -type "string" "[\"|vehicle_ground_GEO|vehicle_ground_GEOShape\"]";
	setAttr -k on ".groundDetection" yes;
	setAttr -k on ".alignWheelsToGround" yes;
	setAttr -k on ".liveGroundEvaluation" yes;
	setAttr -k on ".autoWheelSpin" yes;
	setAttr -k on ".debugGroundRays" yes;
	setAttr -k on ".minimumGroundNormal" 0.15;
	setAttr -k on ".wheelRollMultiplier" 1;
	setAttr ".tcGlobalControl" -type "string" "vehicle_global_CTRL";
	setAttr ".tcChassisControl" -type "string" "vehicle_chassis_CTRL";
	setAttr ".tcAutoSteerInitialized" yes;
	setAttr ".tcAutoSteerPreviousY" 65;
	setAttr ".tcAutoSteerPreviousForwardZ" 1;
	setAttr ".tcAutoSteerLastTime" 1;
	setAttr ".tcDriveInitialized" yes;
	setAttr ".tcDriveLastTime" 1;
	setAttr ".tcWheelRigMap" -type "string" (
		"[{\"axle\":\"front\",\"control\":\"front_left_wheel_CTRL\",\"ground_debug\":\"front_left_groundRay_DBG\",\"id\":\"front_left\",\"mount\":\"|vehicle_root_JNT|vehicle_chassis_JNT|front_left_mount_JNT\",\"side\":\"left\",\"spin_driver\":\"front_left_spin_DRV\",\"steer_driver\":\"front_left_steer_DRV\",\"suspension_driver\":\"front_left_suspension_DRV\",\"wheel_joint\":\"|vehicle_root_JNT|vehicle_chassis_JNT|front_left_mount_JNT|front_left_wheel_JNT\"},{\"axle\":\"front\",\"control\":\"front_right_wheel_CTRL\",\"ground_debug\":\"front_right_groundRay_DBG\",\"id\":\"front_right\",\"mount\":\"|vehicle_root_JNT|vehicle_chassis_JNT|front_right_mount_JNT\",\"side\":\"right\",\"spin_driver\":\"front_right_spin_DRV\",\"steer_driver\":\"front_right_steer_DRV\",\"suspension_driver\":\"front_right_suspension_DRV\",\"wheel_joint\":\"|vehicle_root_JNT|vehicle_chassis_JNT|front_right_mount_JNT|front_right_wheel_JNT\"},{\"axle\":\"rear\",\"control\":\"rear_left_wheel_CTRL\",\"ground_debug\":\"rear_left_groundRay_DBG\",\"id\":\"rear_left\",\"mount\":\"|vehicle_root_JNT|vehicle_chassis_JNT|rear_left_mount_JNT\",\"side\":\"left\",\"spin_driver\":\"rear_left_spin_DRV\",\"steer_driver\":\"rear_left_steer_DRV\",\"suspension_driver\":\"rear_left_suspension_DRV\",\"wheel_joint\":\"|vehicle_root_JNT|vehicle_chassis_JNT|rear_left_mount_JNT|rear_left_wheel_JNT\"},{\"axle\":\"rear\",\"control\":\"rear_right_wheel_CTRL\",\"ground_debug\":\"rear_right_groundRay_DBG\",\"id\":\"rear_right\",\"mount\":\"|vehicle_root_JNT|vehicle_chassis_JNT|rear_right_mount_JNT\",\"side\":\"right\",\"spin_driver\":\"rear_right_spin_DRV\",\"steer_driver\":\"rear_right_steer_DRV\",\"suspension_driver\":\"rear_right_suspension_DRV\",\"wheel_joint\":\"|vehicle_root_JNT|vehicle_chassis_JNT|rear_right_mount_JNT|rear_right_wheel_JNT\"}]");
createNode transform -n "vehicle_controls_GRP" -p "vehicle_RIG";
	rename -uid "4FDA83A4-4A57-C4E6-DCDF-8F9D39A245E5";
createNode transform -n "vehicle_global_CTRL" -p "vehicle_controls_GRP";
	rename -uid "3FA9CCE1-479C-38C1-EBE6-0EB768C8785D";
createNode nurbsCurve -n "curveShape1" -p "vehicle_global_CTRL";
	rename -uid "D20EDFEC-4E89-82C6-FF33-0EA843422489";
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
	rename -uid "CE1D15E0-496D-B816-AE01-13B914817C3F";
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
	setAttr -k on ".maximumSteerAngle" 32;
	setAttr -k on ".ackermann" 1;
	setAttr -k on ".autoSteering" yes;
	setAttr -k on ".autoSteerBlend" 1;
	setAttr -k on ".steeringDrivesMotion" yes;
createNode nurbsCurve -n "curveShape2" -p "vehicle_chassis_CTRL";
	rename -uid "52715D42-4654-C7B4-EA1A-CDA881D39B74";
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
	rename -uid "2710EFAE-494A-77E2-0D93-F289E2666F64";
createNode transform -n "front_left_suspension_DRV" -p "vehicle_solver_GRP";
	rename -uid "40F66B7B-47DD-2529-FB63-1B85994BB4EC";
	setAttr ".t" -type "double3" -80 34 120 ;
createNode transform -n "front_left_steer_DRV" -p "front_left_suspension_DRV";
	rename -uid "94397886-4F1E-5452-01E3-2E9F9738322F";
createNode transform -n "front_left_spin_DRV" -p "front_left_steer_DRV";
	rename -uid "1366F0CA-48CE-85D3-BA64-4C9F366C34C6";
createNode transform -n "front_left_wheel_CTRL" -p "front_left_spin_DRV";
	rename -uid "E4E1F716-4B95-1684-E6D3-FFA103742EEB";
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
	setAttr ".tcRollInitialized" yes;
	setAttr ".tcPreviousWorldX" -80;
	setAttr ".tcPreviousWorldY" 34;
	setAttr ".tcPreviousWorldZ" 120;
	setAttr ".tcPreviousForwardZ" 1;
	setAttr ".tcLastEvaluationTime" 1;
	setAttr ".tcWheelId" -type "string" "front_left";
createNode nurbsCurve -n "front_left_wheel_CTRLShape" -p "front_left_wheel_CTRL";
	rename -uid "375917AD-445F-21FB-F39F-FEA7A0B5DE6F";
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
	rename -uid "A33D1579-47E7-0D66-B933-E69292A66165";
	setAttr ".t" -type "double3" 80 34 120 ;
createNode transform -n "front_right_steer_DRV" -p "front_right_suspension_DRV";
	rename -uid "B5531F0D-47C8-322E-97BE-68A2B3DE695D";
createNode transform -n "front_right_spin_DRV" -p "front_right_steer_DRV";
	rename -uid "D8D3234A-4C32-9C67-B883-4497EAA40978";
createNode transform -n "front_right_wheel_CTRL" -p "front_right_spin_DRV";
	rename -uid "D3847BB9-4CBF-8B76-41ED-11AD7DCCC925";
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
	setAttr ".tcRollInitialized" yes;
	setAttr ".tcPreviousWorldX" 80;
	setAttr ".tcPreviousWorldY" 34;
	setAttr ".tcPreviousWorldZ" 120;
	setAttr ".tcPreviousForwardZ" 1;
	setAttr ".tcLastEvaluationTime" 1;
	setAttr ".tcWheelId" -type "string" "front_right";
createNode nurbsCurve -n "front_right_wheel_CTRLShape" -p "front_right_wheel_CTRL";
	rename -uid "1B434D3C-4622-2550-AD66-A8AEFE37BA44";
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
	rename -uid "665538DB-4FBC-19E9-6E24-0A8A9C1781C2";
	setAttr ".t" -type "double3" -80 34 -120 ;
createNode transform -n "rear_left_steer_DRV" -p "rear_left_suspension_DRV";
	rename -uid "8C18797E-487A-1D6A-EA54-EAAFC42D49E8";
createNode transform -n "rear_left_spin_DRV" -p "rear_left_steer_DRV";
	rename -uid "6CFEDE44-42D9-D3DA-56E3-3BB7E001ADE0";
createNode transform -n "rear_left_wheel_CTRL" -p "rear_left_spin_DRV";
	rename -uid "F0C18D26-4BAD-4C8D-58CB-B1B7B6429DD8";
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
	setAttr ".tcRollInitialized" yes;
	setAttr ".tcPreviousWorldX" -80;
	setAttr ".tcPreviousWorldY" 34;
	setAttr ".tcPreviousWorldZ" -120;
	setAttr ".tcPreviousForwardZ" 1;
	setAttr ".tcLastEvaluationTime" 1;
	setAttr ".tcWheelId" -type "string" "rear_left";
createNode nurbsCurve -n "rear_left_wheel_CTRLShape" -p "rear_left_wheel_CTRL";
	rename -uid "14EA195A-48CC-1AF2-8483-5EBF93A16FFD";
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
	rename -uid "E6DD989A-42C9-D49F-0E57-B993C0248A11";
	setAttr ".t" -type "double3" 80 34 -120 ;
createNode transform -n "rear_right_steer_DRV" -p "rear_right_suspension_DRV";
	rename -uid "D66BC1B5-423F-71A8-BEF4-01A3700CDE76";
createNode transform -n "rear_right_spin_DRV" -p "rear_right_steer_DRV";
	rename -uid "59D575D6-415B-175A-ECEB-BCACC415BAB0";
createNode transform -n "rear_right_wheel_CTRL" -p "rear_right_spin_DRV";
	rename -uid "21913346-4022-7290-4322-B5BCBC29FFBA";
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
	setAttr ".tcRollInitialized" yes;
	setAttr ".tcPreviousWorldX" 80;
	setAttr ".tcPreviousWorldY" 34;
	setAttr ".tcPreviousWorldZ" -120;
	setAttr ".tcPreviousForwardZ" 1;
	setAttr ".tcLastEvaluationTime" 1;
	setAttr ".tcWheelId" -type "string" "rear_right";
createNode nurbsCurve -n "rear_right_wheel_CTRLShape" -p "rear_right_wheel_CTRL";
	rename -uid "F0986C68-4836-40B6-3EB1-3E85A36C5072";
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
	rename -uid "274EAFD1-477F-AE60-F165-40BDB49FA85E";
createNode transform -n "front_left_groundRay_DBG" -p "vehicle_ground_debug_GRP";
	rename -uid "7DDAA716-4236-4F38-476E-ADB3E286C8A2";
createNode nurbsCurve -n "curveShape3" -p "front_left_groundRay_DBG";
	rename -uid "89F44154-40FE-BAF5-51FD-E5BDBC8E96CF";
	setAttr -k off ".v";
	setAttr ".ove" yes;
	setAttr ".ovc" 14;
	setAttr ".cc" -type "nurbsCurve" 
		1 1 0 no 3
		2 0 1
		2
		-80 52 120
		-80 0 120
		;
createNode transform -n "front_right_groundRay_DBG" -p "vehicle_ground_debug_GRP";
	rename -uid "DEB6CBAB-4771-9FD7-1B90-8FA8F44608D0";
createNode nurbsCurve -n "curveShape4" -p "front_right_groundRay_DBG";
	rename -uid "C4460E29-42DF-A662-2D35-3EA164A61B45";
	setAttr -k off ".v";
	setAttr ".ove" yes;
	setAttr ".ovc" 14;
	setAttr ".cc" -type "nurbsCurve" 
		1 1 0 no 3
		2 0 1
		2
		80 52 120
		80 0 120
		;
createNode transform -n "rear_left_groundRay_DBG" -p "vehicle_ground_debug_GRP";
	rename -uid "02D0A978-4C2E-09A4-D7B1-EF851082B712";
createNode nurbsCurve -n "curveShape5" -p "rear_left_groundRay_DBG";
	rename -uid "1542D5C2-4337-B863-98D2-3E968363D728";
	setAttr -k off ".v";
	setAttr ".ove" yes;
	setAttr ".ovc" 14;
	setAttr ".cc" -type "nurbsCurve" 
		1 1 0 no 3
		2 0 1
		2
		-80 52 -120
		-80 0 -120
		;
createNode transform -n "rear_right_groundRay_DBG" -p "vehicle_ground_debug_GRP";
	rename -uid "98D98EA7-4300-042C-40D0-C093A6D350C4";
createNode nurbsCurve -n "curveShape6" -p "rear_right_groundRay_DBG";
	rename -uid "22BFC7A1-4893-226F-5259-41B6F51CFD3C";
	setAttr -k off ".v";
	setAttr ".ove" yes;
	setAttr ".ovc" 14;
	setAttr ".cc" -type "nurbsCurve" 
		1 1 0 no 3
		2 0 1
		2
		80 52 -120
		80 0 -120
		;
createNode transform -n "vehicle_preview_geo_GRP" -p "vehicle_RIG";
	rename -uid "745DF9F7-4F95-E889-8FB9-E4A0A08F4E34";
createNode transform -n "front_left_preview_GEO" -p "vehicle_preview_geo_GRP";
	rename -uid "3A67AC37-490A-8B1E-B0D7-E19F2BE0808E";
createNode mesh -n "front_left_preview_GEOShape" -p "front_left_preview_GEO";
	rename -uid "5E45A8A5-48CC-7A25-F46D-458601AAC2A4";
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
	rename -uid "7449869D-4B5D-B189-1860-D0A19FDD0D21";
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
	rename -uid "82581477-42AB-C928-DB3B-64B7F514D4F8";
createNode mesh -n "front_right_preview_GEOShape" -p "front_right_preview_GEO";
	rename -uid "3AECC70E-4611-B3C8-CD7C-7198D1BD5C7D";
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
	rename -uid "A526B753-4CCB-1FCA-C7FF-C3921C051AC0";
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
	rename -uid "8600764D-4F9F-F219-8692-0AB06D279B7C";
createNode mesh -n "rear_left_preview_GEOShape" -p "rear_left_preview_GEO";
	rename -uid "DCA2C6DB-4BDC-190F-EBB9-2EA96A0BE705";
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
	rename -uid "C04F7DBB-443F-370E-1C62-42A9B00DDD5D";
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
	rename -uid "47171E2D-46B9-FE0C-38AF-9BABDA7EAEAF";
createNode mesh -n "rear_right_preview_GEOShape" -p "rear_right_preview_GEO";
	rename -uid "7FF05A19-4AFF-8DD1-C90D-D4B8846CF19F";
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
	rename -uid "0BC3FB2A-4CF7-60AB-557E-C7BAE1DEF1F0";
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
	rename -uid "FC2FC30B-4909-98E2-66C0-959D96D20DD7";
createNode mesh -n "vehicle_chassis_preview_GEOShape" -p "vehicle_chassis_preview_GEO";
	rename -uid "8661698C-4703-4C80-7C82-22B0B2C32A8B";
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
	rename -uid "20494BAA-4AA6-186D-C899-4DA96C197C9F";
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
createNode transform -n "vehicle_ground_GEO";
	rename -uid "F3348D87-485E-EA31-FDD6-BAA73FDCE4C9";
createNode mesh -n "vehicle_ground_GEOShape" -p "vehicle_ground_GEO";
	rename -uid "40421041-4E64-7E09-EA0F-87971FC289AD";
	setAttr -k off ".v";
	setAttr ".vir" yes;
	setAttr ".vif" yes;
	setAttr ".uvst[0].uvsn" -type "string" "map1";
	setAttr ".cuvs" -type "string" "map1";
	setAttr ".dcc" -type "string" "Diffuse";
	setAttr ".covm[0]"  0 1 1;
	setAttr ".cdvm[0]"  0 1 1;
	setAttr ".ndt" 0;
createNode lightLinker -s -n "lightLinker1";
	rename -uid "AA94E105-460E-F250-A65C-43894BCF5006";
	setAttr -s 2 ".lnk";
	setAttr -s 2 ".slnk";
createNode displayLayerManager -n "layerManager";
	rename -uid "1A4777AE-448D-1C0D-5CF0-C3A1D10A2D35";
createNode displayLayer -n "defaultLayer";
	rename -uid "A3FCED3E-4EE8-41E9-8651-1A9AA40E87C8";
	setAttr ".ufem" -type "stringArray" 0  ;
createNode renderLayerManager -n "renderLayerManager";
	rename -uid "1404DC94-44AE-81EB-D74A-019BD61A7D98";
createNode renderLayer -n "defaultRenderLayer";
	rename -uid "4E9FF3C9-4A5C-C370-3D57-31B558D42C51";
	setAttr ".g" yes;
createNode script -n "uiConfigurationScriptNode";
	rename -uid "B65CA9F3-4FC7-612D-3EFF-E68297454E6C";
	setAttr ".b" -type "string" "// Maya Mel UI Configuration File.\n// No UI generated in batch mode.\n";
	setAttr ".st" 3;
createNode script -n "sceneConfigurationScriptNode";
	rename -uid "848EAE7F-494A-DE1A-91DB-B0B4564C1CC6";
	setAttr ".b" -type "string" "playbackOptions -min 1 -max 120 -ast 1 -aet 200 ";
	setAttr ".st" 6;
createNode polyCylinder -n "polyCylinder1";
	rename -uid "4B7646D4-4398-CF3C-3674-33868C49A647";
	setAttr ".ax" -type "double3" 1 0 0 ;
	setAttr ".r" 34;
	setAttr ".h" 22.1;
	setAttr ".sa" 24;
	setAttr ".sc" 1;
createNode polyCylinder -n "polyCylinder2";
	rename -uid "0ADFE1A4-4702-303C-5D78-76804DF8D81E";
	setAttr ".ax" -type "double3" 1 0 0 ;
	setAttr ".r" 34;
	setAttr ".h" 22.1;
	setAttr ".sa" 24;
	setAttr ".sc" 1;
createNode polyCylinder -n "polyCylinder3";
	rename -uid "0B02619F-4BC5-9439-BB14-92845FD42352";
	setAttr ".ax" -type "double3" 1 0 0 ;
	setAttr ".r" 34;
	setAttr ".h" 22.1;
	setAttr ".sa" 24;
	setAttr ".sc" 1;
createNode polyCylinder -n "polyCylinder4";
	rename -uid "646CB7C3-4F76-DF20-905C-2CA51866D9B1";
	setAttr ".ax" -type "double3" 1 0 0 ;
	setAttr ".r" 34;
	setAttr ".h" 22.1;
	setAttr ".sa" 24;
	setAttr ".sc" 1;
createNode polyCube -n "polyCube1";
	rename -uid "59E303D1-4A1C-35BB-7E28-6688A2A82C2A";
	setAttr ".w" 176;
	setAttr ".h" 50;
	setAttr ".d" 300;
createNode polyPlane -n "polyPlane1";
	rename -uid "CD51D343-45BA-FD74-6674-76993DCCA54E";
	setAttr ".w" 1000;
	setAttr ".h" 1000;
	setAttr ".sw" 20;
	setAttr ".sh" 20;
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
connectAttr "polyPlane1.out" "vehicle_ground_GEOShape.i";
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
connectAttr "vehicle_ground_GEOShape.iog" ":initialShadingGroup.dsm" -na;
// End of vehicle_rig.ma
