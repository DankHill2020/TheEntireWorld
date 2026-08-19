FString UAIStudioBridgeLibrary::CreatePoseSearchSchema(
    const FString& SkeletonPath,
    const FString& AssetPath,
    int32 SampleRate)
{
    const TSharedRef<FJsonObject> Root = MakeShared<FJsonObject>();
    Root->SetStringField(TEXT("capability"), TEXT("create_pose_search_schema"));
    Root->SetStringField(TEXT("python_call"), TEXT("unreal.AIStudioBridgeLibrary.create_pose_search_schema(skeleton_path, asset_path, sample_rate)"));
    Root->SetBoolField(TEXT("ok"), false);
#if WITH_EDITOR
    USkeleton* Skeleton = Cast<USkeleton>(AIStudioLoadAssetObject(SkeletonPath));
    if (!Skeleton || AssetPath.IsEmpty())
    {
        Root->SetStringField(TEXT("status"), Skeleton ? TEXT("invalid_asset_path") : TEXT("skeleton_not_found"));
        return AIStudioJsonString(Root);
    }
    const FString PackageName = AIStudioPackageNameFromAssetPath(AssetPath);
    UPackage* Package = CreatePackage(*PackageName);
    UPoseSearchSchema* Schema = Package
        ? NewObject<UPoseSearchSchema>(Package, FName(*AIStudioAssetNameFromAssetPath(AssetPath)), RF_Public | RF_Standalone | RF_Transactional)
        : nullptr;
    if (!Schema)
    {
        Root->SetStringField(TEXT("status"), TEXT("asset_create_failed"));
        return AIStudioJsonString(Root);
    }
    Schema->Modify();
    Schema->SampleRate = FMath::Clamp(SampleRate, 1, 240);
    Schema->AddSkeleton(Skeleton);
    Schema->PostEditChange();
    FAssetRegistryModule::AssetCreated(Schema);
    const bool bSaved = AIStudioSaveAssetPackage(Schema);
    Root->SetBoolField(TEXT("ok"), bSaved && Schema->GetRoledSkeletons().Num() == 1);
    Root->SetStringField(TEXT("status"), bSaved ? TEXT("created_and_saved") : TEXT("save_failed"));
    Root->SetStringField(TEXT("asset_path"), Schema->GetPathName());
    Root->SetNumberField(TEXT("sample_rate"), Schema->SampleRate);
    Root->SetNumberField(TEXT("skeleton_count"), Schema->GetRoledSkeletons().Num());
#else
    Root->SetStringField(TEXT("status"), TEXT("editor_only"));
#endif
    return AIStudioJsonString(Root);
}

FString UAIStudioBridgeLibrary::AddPoseSearchSchemaChannel(
    const FString& SchemaPath,
    const FString& ChannelClassPath,
    const FString& SettingsJson)
{
    const TSharedRef<FJsonObject> Root = MakeShared<FJsonObject>();
    Root->SetStringField(TEXT("capability"), TEXT("add_pose_search_schema_channel"));
    Root->SetStringField(TEXT("python_call"), TEXT("unreal.AIStudioBridgeLibrary.add_pose_search_schema_channel(schema_path, channel_class_path, settings_json)"));
    Root->SetBoolField(TEXT("ok"), false);
#if WITH_EDITOR
    UPoseSearchSchema* Schema = Cast<UPoseSearchSchema>(AIStudioLoadAssetObject(SchemaPath));
    UClass* ChannelClass = LoadClass<UPoseSearchFeatureChannel>(nullptr, *ChannelClassPath);
    if (!Schema || !ChannelClass || !ChannelClass->IsChildOf(UPoseSearchFeatureChannel::StaticClass()))
    {
        Root->SetStringField(TEXT("status"), Schema ? TEXT("channel_class_not_found") : TEXT("schema_not_found"));
        return AIStudioJsonString(Root);
    }
    UPoseSearchFeatureChannel* Channel = NewObject<UPoseSearchFeatureChannel>(Schema, ChannelClass, NAME_None, RF_Transactional);
    TArray<FString> Errors;
    TSharedPtr<FJsonObject> Settings = AIStudioParseJsonObject(SettingsJson.IsEmpty() ? TEXT("{}") : SettingsJson);
    Schema->Modify();
    Channel->Modify();
    const bool bApplied = Settings.IsValid() && AIStudioSetPropertiesFromJson(Channel, Settings, Errors);
    Schema->AddChannel(Channel);
    Schema->PostEditChange();
    const bool bSaved = AIStudioSaveAssetPackage(Schema);
    Root->SetBoolField(TEXT("ok"), bSaved && bApplied && Errors.IsEmpty());
    Root->SetStringField(TEXT("status"), bSaved ? (Errors.IsEmpty() ? TEXT("channel_added_and_saved") : TEXT("property_errors")) : TEXT("save_failed"));
    Root->SetStringField(TEXT("channel_class"), Channel->GetClass()->GetPathName());
    Root->SetNumberField(TEXT("channel_count"), Schema->GetChannels().Num());
    TArray<TSharedPtr<FJsonValue>> ErrorValues;
    for (const FString& Error : Errors)
    {
        ErrorValues.Add(MakeShared<FJsonValueString>(Error));
    }
    Root->SetArrayField(TEXT("property_errors"), ErrorValues);
#else
    Root->SetStringField(TEXT("status"), TEXT("editor_only"));
#endif
    return AIStudioJsonString(Root);
}

FString UAIStudioBridgeLibrary::CreatePoseSearchDatabase(const FString& SchemaPath, const FString& AssetPath)
{
    const TSharedRef<FJsonObject> Root = MakeShared<FJsonObject>();
    Root->SetStringField(TEXT("capability"), TEXT("create_pose_search_database"));
    Root->SetStringField(TEXT("python_call"), TEXT("unreal.AIStudioBridgeLibrary.create_pose_search_database(schema_path, asset_path)"));
    Root->SetBoolField(TEXT("ok"), false);
#if WITH_EDITOR
    UPoseSearchSchema* Schema = Cast<UPoseSearchSchema>(AIStudioLoadAssetObject(SchemaPath));
    if (!Schema || AssetPath.IsEmpty())
    {
        Root->SetStringField(TEXT("status"), Schema ? TEXT("invalid_asset_path") : TEXT("schema_not_found"));
        return AIStudioJsonString(Root);
    }
    const FString PackageName = AIStudioPackageNameFromAssetPath(AssetPath);
    UPackage* Package = CreatePackage(*PackageName);
    UPoseSearchDatabase* Database = Package
        ? NewObject<UPoseSearchDatabase>(Package, FName(*AIStudioAssetNameFromAssetPath(AssetPath)), RF_Public | RF_Standalone | RF_Transactional)
        : nullptr;
    if (!Database)
    {
        Root->SetStringField(TEXT("status"), TEXT("asset_create_failed"));
        return AIStudioJsonString(Root);
    }
    Database->Modify();
    Database->Schema = Schema;
    Database->PostEditChange();
    FAssetRegistryModule::AssetCreated(Database);
    const bool bSaved = AIStudioSaveAssetPackage(Database);
    Root->SetBoolField(TEXT("ok"), bSaved && Database->Schema == Schema);
    Root->SetStringField(TEXT("status"), bSaved ? TEXT("created_and_saved") : TEXT("save_failed"));
    Root->SetStringField(TEXT("asset_path"), Database->GetPathName());
    Root->SetStringField(TEXT("schema_path"), Schema->GetPathName());
    Root->SetNumberField(TEXT("animation_count"), Database->GetNumAnimationAssets());
#else
    Root->SetStringField(TEXT("status"), TEXT("editor_only"));
#endif
    return AIStudioJsonString(Root);
}

FString UAIStudioBridgeLibrary::AddPoseSearchAnimation(const FString& DatabasePath, const FString& AnimationPath)
{
    const TSharedRef<FJsonObject> Root = MakeShared<FJsonObject>();
    Root->SetStringField(TEXT("capability"), TEXT("add_pose_search_animation"));
    Root->SetStringField(TEXT("python_call"), TEXT("unreal.AIStudioBridgeLibrary.add_pose_search_animation(database_path, animation_path)"));
    Root->SetBoolField(TEXT("ok"), false);
#if WITH_EDITOR
    UPoseSearchDatabase* Database = Cast<UPoseSearchDatabase>(AIStudioLoadAssetObject(DatabasePath));
    UObject* Animation = AIStudioLoadAssetObject(AnimationPath);
    if (!Database || !Animation)
    {
        Root->SetStringField(TEXT("status"), Database ? TEXT("animation_not_found") : TEXT("database_not_found"));
        return AIStudioJsonString(Root);
    }
    for (int32 Index = 0; Index < Database->GetNumAnimationAssets(); ++Index)
    {
        if (Database->GetAnimationAsset(Index) == Animation)
        {
            Root->SetBoolField(TEXT("ok"), true);
            Root->SetStringField(TEXT("status"), TEXT("already_present"));
            Root->SetNumberField(TEXT("animation_count"), Database->GetNumAnimationAssets());
            return AIStudioJsonString(Root);
        }
    }
    Database->Modify();
    FPoseSearchDatabaseAnimationAsset Entry;
    Entry.AnimAsset = Animation;
    Database->AddAnimationAsset(Entry);
    Database->PostEditChange();
    const bool bSaved = AIStudioSaveAssetPackage(Database);
    Root->SetBoolField(TEXT("ok"), bSaved);
    Root->SetStringField(TEXT("status"), bSaved ? TEXT("animation_added_and_saved") : TEXT("save_failed"));
    Root->SetNumberField(TEXT("animation_count"), Database->GetNumAnimationAssets());
#else
    Root->SetStringField(TEXT("status"), TEXT("editor_only"));
#endif
    return AIStudioJsonString(Root);
}

FString UAIStudioBridgeLibrary::RemovePoseSearchAnimation(const FString& DatabasePath, const FString& AnimationPath)
{
    const TSharedRef<FJsonObject> Root = MakeShared<FJsonObject>();
    Root->SetStringField(TEXT("capability"), TEXT("remove_pose_search_animation"));
    Root->SetStringField(TEXT("python_call"), TEXT("unreal.AIStudioBridgeLibrary.remove_pose_search_animation(database_path, animation_path)"));
    Root->SetBoolField(TEXT("ok"), false);
#if WITH_EDITOR
    UPoseSearchDatabase* Database = Cast<UPoseSearchDatabase>(AIStudioLoadAssetObject(DatabasePath));
    UObject* Animation = AIStudioLoadAssetObject(AnimationPath);
    if (!Database || !Animation)
    {
        Root->SetStringField(TEXT("status"), Database ? TEXT("animation_not_found") : TEXT("database_not_found"));
        return AIStudioJsonString(Root);
    }
    int32 FoundIndex = INDEX_NONE;
    for (int32 Index = 0; Index < Database->GetNumAnimationAssets(); ++Index)
    {
        if (Database->GetAnimationAsset(Index) == Animation)
        {
            FoundIndex = Index;
            break;
        }
    }
    if (FoundIndex == INDEX_NONE)
    {
        Root->SetStringField(TEXT("status"), TEXT("animation_not_present"));
        return AIStudioJsonString(Root);
    }
    Database->Modify();
    Database->RemoveAnimationAssetAt(FoundIndex);
    Database->PostEditChange();
    const bool bSaved = AIStudioSaveAssetPackage(Database);
    Root->SetBoolField(TEXT("ok"), bSaved);
    Root->SetStringField(TEXT("status"), bSaved ? TEXT("animation_removed_and_saved") : TEXT("save_failed"));
    Root->SetNumberField(TEXT("animation_count"), Database->GetNumAnimationAssets());
#else
    Root->SetStringField(TEXT("status"), TEXT("editor_only"));
#endif
    return AIStudioJsonString(Root);
}

FString UAIStudioBridgeLibrary::CreatePhysicsAsset(
    const FString& SkeletalMeshPath,
    const FString& AssetPath,
    bool bAssignToMesh)
{
    const TSharedRef<FJsonObject> Root = MakeShared<FJsonObject>();
    Root->SetStringField(TEXT("capability"), TEXT("create_physics_asset"));
    Root->SetStringField(TEXT("python_call"), TEXT("unreal.AIStudioBridgeLibrary.create_physics_asset(skeletal_mesh_path, asset_path, assign_to_mesh)"));
    Root->SetBoolField(TEXT("ok"), false);
#if WITH_EDITOR
    USkeletalMesh* Mesh = Cast<USkeletalMesh>(AIStudioLoadAssetObject(SkeletalMeshPath));
    if (!Mesh || AssetPath.IsEmpty())
    {
        Root->SetStringField(TEXT("status"), Mesh ? TEXT("invalid_asset_path") : TEXT("skeletal_mesh_not_found"));
        return AIStudioJsonString(Root);
    }
    const FString PackageName = AIStudioPackageNameFromAssetPath(AssetPath);
    UPackage* Package = CreatePackage(*PackageName);
    UPhysicsAsset* PhysicsAsset = Package
        ? Cast<UPhysicsAsset>(UPhysicsAssetFactory::CreatePhysicsAssetFromMesh(
            FName(*AIStudioAssetNameFromAssetPath(AssetPath)), Package, Mesh, bAssignToMesh))
        : nullptr;
    if (!PhysicsAsset)
    {
        Root->SetStringField(TEXT("status"), TEXT("physics_asset_create_failed"));
        return AIStudioJsonString(Root);
    }
    FAssetRegistryModule::AssetCreated(PhysicsAsset);
    const bool bSaved = AIStudioSaveAssetPackage(PhysicsAsset);
    Root->SetBoolField(TEXT("ok"), bSaved && PhysicsAsset->SkeletalBodySetups.Num() > 0);
    Root->SetStringField(TEXT("status"), bSaved ? TEXT("created_and_saved") : TEXT("save_failed"));
    Root->SetStringField(TEXT("asset_path"), PhysicsAsset->GetPathName());
    Root->SetNumberField(TEXT("body_count"), PhysicsAsset->SkeletalBodySetups.Num());
    Root->SetNumberField(TEXT("constraint_count"), PhysicsAsset->ConstraintSetup.Num());
#else
    Root->SetStringField(TEXT("status"), TEXT("editor_only"));
#endif
    return AIStudioJsonString(Root);
}

FString UAIStudioBridgeLibrary::AddPhysicsBody(
    const FString& PhysicsAssetPath,
    FName BoneName,
    const FString& ShapeType)
{
    const TSharedRef<FJsonObject> Root = MakeShared<FJsonObject>();
    Root->SetStringField(TEXT("capability"), TEXT("add_physics_body"));
    Root->SetStringField(TEXT("python_call"), TEXT("unreal.AIStudioBridgeLibrary.add_physics_body(physics_asset_path, bone_name, shape_type)"));
    Root->SetBoolField(TEXT("ok"), false);
#if WITH_EDITOR
    UPhysicsAsset* PhysicsAsset = Cast<UPhysicsAsset>(AIStudioLoadAssetObject(PhysicsAssetPath));
    if (!PhysicsAsset)
    {
        Root->SetStringField(TEXT("status"), TEXT("physics_asset_not_found"));
        return AIStudioJsonString(Root);
    }
    if (USkeletalMesh* PreviewMesh = PhysicsAsset->GetPreviewMesh())
    {
        if (PreviewMesh->GetRefSkeleton().FindBoneIndex(BoneName) == INDEX_NONE)
        {
            Root->SetStringField(TEXT("status"), TEXT("bone_not_found_on_preview_mesh"));
            Root->SetStringField(TEXT("bone_name"), BoneName.ToString());
            Root->SetStringField(TEXT("preview_mesh"), PreviewMesh->GetPathName());
            return AIStudioJsonString(Root);
        }
    }
    if (PhysicsAsset->FindBodyIndex(BoneName) != INDEX_NONE)
    {
        Root->SetBoolField(TEXT("ok"), true);
        Root->SetStringField(TEXT("status"), TEXT("already_present"));
        return AIStudioJsonString(Root);
    }
    PhysicsAsset->Modify();
    FPhysAssetCreateParams Params;
    const int32 BodyIndex = FPhysicsAssetUtils::CreateNewBody(PhysicsAsset, BoneName, Params);
    USkeletalBodySetup* Body = PhysicsAsset->SkeletalBodySetups.IsValidIndex(BodyIndex)
        ? PhysicsAsset->SkeletalBodySetups[BodyIndex].Get()
        : nullptr;
    if (!Body)
    {
        Root->SetStringField(TEXT("status"), TEXT("body_create_failed"));
        return AIStudioJsonString(Root);
    }
    const FString Shape = ShapeType.ToLower();
    if (Shape == TEXT("sphere"))
    {
        FKSphereElem Elem;
        Elem.Radius = 15.0f;
        Body->AggGeom.SphereElems.Add(Elem);
    }
    else if (Shape == TEXT("box"))
    {
        FKBoxElem Elem;
        Elem.X = Elem.Y = Elem.Z = 30.0f;
        Body->AggGeom.BoxElems.Add(Elem);
    }
    else
    {
        FKSphylElem Elem;
        Elem.Radius = 15.0f;
        Elem.Length = 30.0f;
        Body->AggGeom.SphylElems.Add(Elem);
    }
    Body->InvalidatePhysicsData();
    Body->CreatePhysicsMeshes();
    PhysicsAsset->PostEditChange();
    const bool bSaved = AIStudioSaveAssetPackage(PhysicsAsset);
    Root->SetBoolField(TEXT("ok"), bSaved);
    Root->SetStringField(TEXT("status"), bSaved ? TEXT("body_added_and_saved") : TEXT("save_failed"));
    Root->SetNumberField(TEXT("body_index"), BodyIndex);
    Root->SetStringField(TEXT("bone_name"), BoneName.ToString());
    Root->SetStringField(TEXT("shape_type"), Shape);
#else
    Root->SetStringField(TEXT("status"), TEXT("editor_only"));
#endif
    return AIStudioJsonString(Root);
}

FString UAIStudioBridgeLibrary::AddPhysicsConstraint(
    const FString& PhysicsAssetPath,
    FName BoneNameA,
    FName BoneNameB)
{
    const TSharedRef<FJsonObject> Root = MakeShared<FJsonObject>();
    Root->SetStringField(TEXT("capability"), TEXT("add_physics_constraint"));
    Root->SetStringField(TEXT("python_call"), TEXT("unreal.AIStudioBridgeLibrary.add_physics_constraint(physics_asset_path, bone_name_a, bone_name_b)"));
    Root->SetBoolField(TEXT("ok"), false);
#if WITH_EDITOR
    UPhysicsAsset* PhysicsAsset = Cast<UPhysicsAsset>(AIStudioLoadAssetObject(PhysicsAssetPath));
    if (!PhysicsAsset || PhysicsAsset->FindBodyIndex(BoneNameA) == INDEX_NONE || PhysicsAsset->FindBodyIndex(BoneNameB) == INDEX_NONE)
    {
        Root->SetStringField(TEXT("status"), PhysicsAsset ? TEXT("body_not_found") : TEXT("physics_asset_not_found"));
        return AIStudioJsonString(Root);
    }
    for (int32 ExistingIndex = 0; ExistingIndex < PhysicsAsset->ConstraintSetup.Num(); ++ExistingIndex)
    {
        const UPhysicsConstraintTemplate* Existing = PhysicsAsset->ConstraintSetup[ExistingIndex];
        if (!Existing)
        {
            continue;
        }
        const FName ExistingA = Existing->DefaultInstance.ConstraintBone1;
        const FName ExistingB = Existing->DefaultInstance.ConstraintBone2;
        if ((ExistingA == BoneNameA && ExistingB == BoneNameB)
            || (ExistingA == BoneNameB && ExistingB == BoneNameA))
        {
            Root->SetBoolField(TEXT("ok"), true);
            Root->SetStringField(TEXT("status"), TEXT("already_present"));
            Root->SetNumberField(TEXT("constraint_index"), ExistingIndex);
            Root->SetStringField(TEXT("constraint_name"), Existing->GetName());
            return AIStudioJsonString(Root);
        }
    }
    PhysicsAsset->Modify();
    const FName ConstraintName(*FString::Printf(TEXT("%s_to_%s"), *BoneNameA.ToString(), *BoneNameB.ToString()));
    const int32 ConstraintIndex = FPhysicsAssetUtils::CreateNewConstraint(PhysicsAsset, ConstraintName);
    UPhysicsConstraintTemplate* Constraint = PhysicsAsset->ConstraintSetup.IsValidIndex(ConstraintIndex)
        ? PhysicsAsset->ConstraintSetup[ConstraintIndex]
        : nullptr;
    if (!Constraint)
    {
        Root->SetStringField(TEXT("status"), TEXT("constraint_create_failed"));
        return AIStudioJsonString(Root);
    }
    Constraint->DefaultInstance.ConstraintBone1 = BoneNameA;
    Constraint->DefaultInstance.ConstraintBone2 = BoneNameB;
    PhysicsAsset->PostEditChange();
    const bool bSaved = AIStudioSaveAssetPackage(PhysicsAsset);
    Root->SetBoolField(TEXT("ok"), bSaved);
    Root->SetStringField(TEXT("status"), bSaved ? TEXT("constraint_added_and_saved") : TEXT("save_failed"));
    Root->SetNumberField(TEXT("constraint_index"), ConstraintIndex);
    Root->SetStringField(TEXT("constraint_name"), ConstraintName.ToString());
#else
    Root->SetStringField(TEXT("status"), TEXT("editor_only"));
#endif
    return AIStudioJsonString(Root);
}

FString UAIStudioBridgeLibrary::InspectPhysicsAsset(const FString& PhysicsAssetPath)
{
    const TSharedRef<FJsonObject> Root = MakeShared<FJsonObject>();
    Root->SetStringField(TEXT("capability"), TEXT("inspect_physics_asset"));
    Root->SetStringField(TEXT("python_call"), TEXT("unreal.AIStudioBridgeLibrary.inspect_physics_asset(physics_asset_path)"));
    Root->SetBoolField(TEXT("ok"), false);
#if WITH_EDITOR
    UPhysicsAsset* PhysicsAsset = Cast<UPhysicsAsset>(AIStudioLoadAssetObject(PhysicsAssetPath));
    if (!PhysicsAsset)
    {
        Root->SetStringField(TEXT("status"), TEXT("physics_asset_not_found"));
        return AIStudioJsonString(Root);
    }
    TArray<TSharedPtr<FJsonValue>> Bodies;
    for (int32 Index = 0; Index < PhysicsAsset->SkeletalBodySetups.Num(); ++Index)
    {
        const USkeletalBodySetup* Body = PhysicsAsset->SkeletalBodySetups[Index].Get();
        if (!Body)
        {
            continue;
        }
        const TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
        Row->SetNumberField(TEXT("index"), Index);
        Row->SetStringField(TEXT("name"), Body->GetName());
        Row->SetStringField(TEXT("bone_name"), Body->BoneName.ToString());
        Row->SetNumberField(TEXT("sphere_count"), Body->AggGeom.SphereElems.Num());
        Row->SetNumberField(TEXT("box_count"), Body->AggGeom.BoxElems.Num());
        Row->SetNumberField(TEXT("capsule_count"), Body->AggGeom.SphylElems.Num());
        Row->SetNumberField(TEXT("convex_count"), Body->AggGeom.ConvexElems.Num());
        Bodies.Add(MakeShared<FJsonValueObject>(Row));
    }
    TArray<TSharedPtr<FJsonValue>> Constraints;
    for (int32 Index = 0; Index < PhysicsAsset->ConstraintSetup.Num(); ++Index)
    {
        const UPhysicsConstraintTemplate* Constraint = PhysicsAsset->ConstraintSetup[Index];
        if (!Constraint)
        {
            continue;
        }
        const TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
        Row->SetNumberField(TEXT("index"), Index);
        Row->SetStringField(TEXT("name"), Constraint->GetName());
        Row->SetStringField(TEXT("bone_name_a"), Constraint->DefaultInstance.ConstraintBone1.ToString());
        Row->SetStringField(TEXT("bone_name_b"), Constraint->DefaultInstance.ConstraintBone2.ToString());
        Row->SetNumberField(TEXT("profile_count"), Constraint->ProfileHandles.Num());
        Constraints.Add(MakeShared<FJsonValueObject>(Row));
    }
    Root->SetBoolField(TEXT("ok"), true);
    Root->SetStringField(TEXT("status"), TEXT("inspected"));
    Root->SetStringField(TEXT("asset_path"), PhysicsAsset->GetPathName());
    Root->SetNumberField(TEXT("body_count"), Bodies.Num());
    Root->SetNumberField(TEXT("constraint_count"), Constraints.Num());
    Root->SetArrayField(TEXT("bodies"), Bodies);
    Root->SetArrayField(TEXT("constraints"), Constraints);
#else
    Root->SetStringField(TEXT("status"), TEXT("editor_only"));
#endif
    return AIStudioJsonString(Root);
}

FString UAIStudioBridgeLibrary::SetPhysicsBodyProperty(
    const FString& PhysicsAssetPath,
    FName BodyName,
    FName PropertyName,
    const FString& ValueJson)
{
    const TSharedRef<FJsonObject> Root = MakeShared<FJsonObject>();
    Root->SetStringField(TEXT("capability"), TEXT("set_physics_body_property"));
    Root->SetStringField(TEXT("python_call"), TEXT("unreal.AIStudioBridgeLibrary.set_physics_body_property(physics_asset_path, body_name, property_name, value_json)"));
    Root->SetBoolField(TEXT("ok"), false);
#if WITH_EDITOR
    UPhysicsAsset* PhysicsAsset = Cast<UPhysicsAsset>(AIStudioLoadAssetObject(PhysicsAssetPath));
    USkeletalBodySetup* Body = nullptr;
    if (PhysicsAsset)
    {
        const int32 BodyIndex = PhysicsAsset->FindBodyIndex(BodyName);
        Body = PhysicsAsset->SkeletalBodySetups.IsValidIndex(BodyIndex)
            ? PhysicsAsset->SkeletalBodySetups[BodyIndex].Get()
            : nullptr;
        if (!Body)
        {
            const TObjectPtr<USkeletalBodySetup>* Match = PhysicsAsset->SkeletalBodySetups.FindByPredicate(
                [BodyName](const TObjectPtr<USkeletalBodySetup>& Candidate)
                {
                    return Candidate && Candidate->GetFName() == BodyName;
                });
            Body = Match ? Match->Get() : nullptr;
        }
    }
    void* PropertyContainer = Body;
    UStruct* PropertyOwnerStruct = Body ? Body->GetClass() : nullptr;
    FProperty* Property = Body ? AIStudioFindFlexibleProperty(PropertyOwnerStruct, PropertyName) : nullptr;
    FString PropertyScope = TEXT("body_setup");
    if (Body && !Property)
    {
        PropertyContainer = &Body->DefaultInstance;
        PropertyOwnerStruct = FBodyInstance::StaticStruct();
        Property = AIStudioFindFlexibleProperty(PropertyOwnerStruct, PropertyName);
        PropertyScope = TEXT("body_instance");
    }
    if (!PhysicsAsset || !Body || !Property)
    {
        Root->SetStringField(
            TEXT("status"),
            !PhysicsAsset ? TEXT("physics_asset_not_found") : !Body ? TEXT("body_not_found") : TEXT("property_not_found"));
        return AIStudioJsonString(Root);
    }
    const TSharedPtr<FJsonValue> Value = AIStudioParseJsonValueOrString(ValueJson);
    FString Error;
    const FScopedTransaction Transaction(NSLOCTEXT("AIStudioBridge", "SetPhysicsBodyProperty", "AIStudioBridge Set Physics Body Property"));
    PhysicsAsset->Modify();
    Body->Modify();
    const bool bApplied = AIStudioSetPropertyOnContainerFromJsonValue(
        PropertyContainer,
        Body,
        Property,
        Value.Get(),
        Error);
    if (bApplied)
    {
        Body->PostEditChange();
        PhysicsAsset->PostEditChange();
    }
    const bool bSaved = bApplied && AIStudioSaveAssetPackage(PhysicsAsset);
    Root->SetBoolField(TEXT("ok"), bSaved);
    Root->SetStringField(TEXT("status"), bSaved ? TEXT("property_set_and_saved") : TEXT("property_set_failed"));
    Root->SetStringField(TEXT("body_name"), Body->BoneName.ToString());
    Root->SetStringField(TEXT("property_name"), Property->GetName());
    Root->SetStringField(TEXT("property_scope"), PropertyScope);
    Root->SetStringField(TEXT("error"), Error);
    Root->SetObjectField(TEXT("readback"), AIStudioContainerPropertyValue(PropertyContainer, Body, Property));
#else
    Root->SetStringField(TEXT("status"), TEXT("editor_only"));
#endif
    return AIStudioJsonString(Root);
}

FString UAIStudioBridgeLibrary::SetPhysicsConstraintProperty(
    const FString& PhysicsAssetPath,
    FName ConstraintName,
    FName PropertyName,
    const FString& ValueJson)
{
    const TSharedRef<FJsonObject> Root = MakeShared<FJsonObject>();
    Root->SetStringField(TEXT("capability"), TEXT("set_physics_constraint_property"));
    Root->SetStringField(TEXT("python_call"), TEXT("unreal.AIStudioBridgeLibrary.set_physics_constraint_property(physics_asset_path, constraint_name, property_name, value_json)"));
    Root->SetBoolField(TEXT("ok"), false);
#if WITH_EDITOR
    UPhysicsAsset* PhysicsAsset = Cast<UPhysicsAsset>(AIStudioLoadAssetObject(PhysicsAssetPath));
    UPhysicsConstraintTemplate* Constraint = nullptr;
    if (PhysicsAsset)
    {
        const TObjectPtr<UPhysicsConstraintTemplate>* Match = PhysicsAsset->ConstraintSetup.FindByPredicate(
            [ConstraintName](const TObjectPtr<UPhysicsConstraintTemplate>& Candidate)
            {
                return Candidate && Candidate->GetFName() == ConstraintName;
            });
        Constraint = Match ? Match->Get() : nullptr;
    }
    void* PropertyContainer = Constraint;
    FProperty* Property = Constraint ? AIStudioFindFlexibleProperty(Constraint->GetClass(), PropertyName) : nullptr;
    FString PropertyScope = TEXT("constraint_template");
    if (Constraint && !Property)
    {
        PropertyContainer = &Constraint->DefaultInstance;
        Property = AIStudioFindFlexibleProperty(FConstraintInstance::StaticStruct(), PropertyName);
        PropertyScope = TEXT("constraint_instance");
    }
    if (Constraint && !Property)
    {
        PropertyContainer = &Constraint->DefaultInstance.ProfileInstance;
        Property = AIStudioFindFlexibleProperty(FConstraintProfileProperties::StaticStruct(), PropertyName);
        PropertyScope = TEXT("constraint_profile");
    }
    if (!PhysicsAsset || !Constraint || !Property)
    {
        Root->SetStringField(
            TEXT("status"),
            !PhysicsAsset ? TEXT("physics_asset_not_found") : !Constraint ? TEXT("constraint_not_found") : TEXT("property_not_found"));
        return AIStudioJsonString(Root);
    }
    const TSharedPtr<FJsonValue> Value = AIStudioParseJsonValueOrString(ValueJson);
    FString Error;
    const FScopedTransaction Transaction(NSLOCTEXT("AIStudioBridge", "SetPhysicsConstraintProperty", "AIStudioBridge Set Physics Constraint Property"));
    PhysicsAsset->Modify();
    Constraint->Modify();
    const bool bApplied = AIStudioSetPropertyOnContainerFromJsonValue(
        PropertyContainer,
        Constraint,
        Property,
        Value.Get(),
        Error);
    if (bApplied)
    {
        Constraint->PostEditChange();
        PhysicsAsset->PostEditChange();
    }
    const bool bSaved = bApplied && AIStudioSaveAssetPackage(PhysicsAsset);
    Root->SetBoolField(TEXT("ok"), bSaved);
    Root->SetStringField(TEXT("status"), bSaved ? TEXT("property_set_and_saved") : TEXT("property_set_failed"));
    Root->SetStringField(TEXT("constraint_name"), Constraint->GetName());
    Root->SetStringField(TEXT("property_name"), Property->GetName());
    Root->SetStringField(TEXT("property_scope"), PropertyScope);
    Root->SetStringField(TEXT("error"), Error);
    Root->SetObjectField(TEXT("readback"), AIStudioContainerPropertyValue(PropertyContainer, Constraint, Property));
#else
    Root->SetStringField(TEXT("status"), TEXT("editor_only"));
#endif
    return AIStudioJsonString(Root);
}

FString UAIStudioBridgeLibrary::SetPhysicsProfileProperty(
    const FString& PhysicsAssetPath,
    FName ProfileName,
    FName PropertyName,
    const FString& ValueJson)
{
    const TSharedRef<FJsonObject> Root = MakeShared<FJsonObject>();
    Root->SetStringField(TEXT("capability"), TEXT("set_physics_profile_property"));
    Root->SetStringField(TEXT("python_call"), TEXT("unreal.AIStudioBridgeLibrary.set_physics_profile_property(physics_asset_path, profile_name, property_name, value_json)"));
    Root->SetBoolField(TEXT("ok"), false);
#if WITH_EDITOR
    UPhysicsAsset* PhysicsAsset = Cast<UPhysicsAsset>(AIStudioLoadAssetObject(PhysicsAssetPath));
    if (!PhysicsAsset)
    {
        Root->SetStringField(TEXT("status"), TEXT("physics_asset_not_found"));
        return AIStudioJsonString(Root);
    }
    const TSharedPtr<FJsonValue> Value = AIStudioParseJsonValueOrString(ValueJson);
    int32 PhysicalAnimationChanges = 0;
    int32 ConstraintChanges = 0;
    TArray<FString> Errors;
    const FScopedTransaction Transaction(NSLOCTEXT("AIStudioBridge", "SetPhysicsProfileProperty", "AIStudioBridge Set Physics Profile Property"));
    PhysicsAsset->Modify();
    for (USkeletalBodySetup* Body : PhysicsAsset->SkeletalBodySetups)
    {
        FPhysicalAnimationProfile* Profile = Body ? Body->FindPhysicalAnimationProfile(ProfileName) : nullptr;
        FProperty* Property = Profile
            ? AIStudioFindFlexibleProperty(FPhysicalAnimationData::StaticStruct(), PropertyName)
            : nullptr;
        if (!Profile || !Property)
        {
            continue;
        }
        FString Error;
        Body->Modify();
        if (AIStudioSetPropertyOnContainerFromJsonValue(
            &Profile->PhysicalAnimationData,
            Body,
            Property,
            Value.Get(),
            Error))
        {
            ++PhysicalAnimationChanges;
            Body->PostEditChange();
        }
        else
        {
            Errors.Add(Error);
        }
    }
    for (UPhysicsConstraintTemplate* Constraint : PhysicsAsset->ConstraintSetup)
    {
        if (!Constraint)
        {
            continue;
        }
        for (FPhysicsConstraintProfileHandle& Handle : Constraint->ProfileHandles)
        {
            if (Handle.ProfileName != ProfileName)
            {
                continue;
            }
            FProperty* Property = AIStudioFindFlexibleProperty(FConstraintProfileProperties::StaticStruct(), PropertyName);
            if (!Property)
            {
                continue;
            }
            FString Error;
            Constraint->Modify();
            if (AIStudioSetPropertyOnContainerFromJsonValue(
                &Handle.ProfileProperties,
                Constraint,
                Property,
                Value.Get(),
                Error))
            {
                ++ConstraintChanges;
                Constraint->PostEditChange();
            }
            else
            {
                Errors.Add(Error);
            }
        }
    }
    const int32 TotalChanges = PhysicalAnimationChanges + ConstraintChanges;
    if (TotalChanges > 0)
    {
        PhysicsAsset->PostEditChange();
    }
    const bool bSaved = TotalChanges > 0 && Errors.Num() == 0 && AIStudioSaveAssetPackage(PhysicsAsset);
    Root->SetBoolField(TEXT("ok"), bSaved);
    Root->SetStringField(
        TEXT("status"),
        bSaved ? TEXT("profile_property_set_and_saved") : TotalChanges == 0 ? TEXT("profile_or_property_not_found") : TEXT("profile_property_set_failed"));
    Root->SetNumberField(TEXT("physical_animation_changes"), PhysicalAnimationChanges);
    Root->SetNumberField(TEXT("constraint_changes"), ConstraintChanges);
    TArray<TSharedPtr<FJsonValue>> ErrorValues;
    for (const FString& Error : Errors)
    {
        ErrorValues.Add(MakeShared<FJsonValueString>(Error));
    }
    Root->SetArrayField(TEXT("errors"), ErrorValues);
#else
    Root->SetStringField(TEXT("status"), TEXT("editor_only"));
#endif
    return AIStudioJsonString(Root);
}

FString UAIStudioBridgeLibrary::ListPhysicsProfiles(const FString& PhysicsAssetPath)
{
    const TSharedRef<FJsonObject> Root = MakeShared<FJsonObject>();
    Root->SetStringField(TEXT("capability"), TEXT("list_physics_profiles"));
    Root->SetStringField(TEXT("python_call"), TEXT("unreal.AIStudioBridgeLibrary.list_physics_profiles(physics_asset_path)"));
    Root->SetBoolField(TEXT("ok"), false);
#if WITH_EDITOR
    UPhysicsAsset* PhysicsAsset = Cast<UPhysicsAsset>(AIStudioLoadAssetObject(PhysicsAssetPath));
    if (!PhysicsAsset)
    {
        Root->SetStringField(TEXT("status"), TEXT("physics_asset_not_found"));
        return AIStudioJsonString(Root);
    }
    TArray<TSharedPtr<FJsonValue>> PhysicalAnimationProfiles;
    for (const FName ProfileName : PhysicsAsset->GetPhysicalAnimationProfileNames())
    {
        int32 AssignmentCount = 0;
        for (const USkeletalBodySetup* Body : PhysicsAsset->SkeletalBodySetups)
        {
            AssignmentCount += Body && Body->FindPhysicalAnimationProfile(ProfileName) ? 1 : 0;
        }
        const TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
        Row->SetStringField(TEXT("name"), ProfileName.ToString());
        Row->SetNumberField(TEXT("assignment_count"), AssignmentCount);
        PhysicalAnimationProfiles.Add(MakeShared<FJsonValueObject>(Row));
    }
    TArray<TSharedPtr<FJsonValue>> ConstraintProfiles;
    for (const FName ProfileName : PhysicsAsset->GetConstraintProfileNames())
    {
        int32 AssignmentCount = 0;
        for (const UPhysicsConstraintTemplate* Constraint : PhysicsAsset->ConstraintSetup)
        {
            AssignmentCount += Constraint && Constraint->ContainsConstraintProfile(ProfileName) ? 1 : 0;
        }
        const TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
        Row->SetStringField(TEXT("name"), ProfileName.ToString());
        Row->SetNumberField(TEXT("assignment_count"), AssignmentCount);
        ConstraintProfiles.Add(MakeShared<FJsonValueObject>(Row));
    }
    Root->SetBoolField(TEXT("ok"), true);
    Root->SetStringField(TEXT("status"), TEXT("profiles_inspected"));
    Root->SetStringField(TEXT("asset_path"), PhysicsAsset->GetPathName());
    Root->SetArrayField(TEXT("physical_animation_profiles"), PhysicalAnimationProfiles);
    Root->SetArrayField(TEXT("constraint_profiles"), ConstraintProfiles);
#else
    Root->SetStringField(TEXT("status"), TEXT("editor_only"));
#endif
    return AIStudioJsonString(Root);
}

FString UAIStudioBridgeLibrary::AddPhysicsProfile(
    const FString& PhysicsAssetPath,
    FName ProfileName,
    const FString& ProfileType,
    bool bAssignAll)
{
    const TSharedRef<FJsonObject> Root = MakeShared<FJsonObject>();
    Root->SetStringField(TEXT("capability"), TEXT("add_physics_profile"));
    Root->SetStringField(TEXT("python_call"), TEXT("unreal.AIStudioBridgeLibrary.add_physics_profile(physics_asset_path, profile_name, profile_type, assign_all)"));
    Root->SetBoolField(TEXT("ok"), false);
#if WITH_EDITOR
    UPhysicsAsset* PhysicsAsset = Cast<UPhysicsAsset>(AIStudioLoadAssetObject(PhysicsAssetPath));
    const FString NormalizedType = ProfileType.TrimStartAndEnd().ToLower();
    const bool bPhysicalAnimation = NormalizedType == TEXT("physical_animation") || NormalizedType == TEXT("physical");
    const bool bConstraint = NormalizedType == TEXT("constraint") || NormalizedType == TEXT("constraints");
    if (!PhysicsAsset || ProfileName.IsNone() || (!bPhysicalAnimation && !bConstraint))
    {
        Root->SetStringField(
            TEXT("status"),
            !PhysicsAsset ? TEXT("physics_asset_not_found") : ProfileName.IsNone() ? TEXT("profile_name_required") : TEXT("invalid_profile_type"));
        return AIStudioJsonString(Root);
    }
    const FScopedTransaction Transaction(NSLOCTEXT("AIStudioBridge", "AddPhysicsProfile", "AIStudioBridge Add Physics Profile"));
    PhysicsAsset->Modify();
    int32 AssignmentCount = 0;
    bool bCreated = false;
    if (bPhysicalAnimation)
    {
        TArray<FName>& Names = const_cast<TArray<FName>&>(PhysicsAsset->GetPhysicalAnimationProfileNames());
        bCreated = !Names.Contains(ProfileName);
        Names.AddUnique(ProfileName);
        if (bAssignAll)
        {
            for (USkeletalBodySetup* Body : PhysicsAsset->SkeletalBodySetups)
            {
                if (!Body || Body->FindPhysicalAnimationProfile(ProfileName))
                {
                    AssignmentCount += Body ? 1 : 0;
                    continue;
                }
                Body->Modify();
                Body->CurrentPhysicalAnimationProfile = FPhysicalAnimationProfile();
                Body->AddPhysicalAnimationProfile(ProfileName);
                Body->PostEditChange();
                ++AssignmentCount;
            }
        }
    }
    else
    {
        TArray<FName>& Names = const_cast<TArray<FName>&>(PhysicsAsset->GetConstraintProfileNames());
        bCreated = !Names.Contains(ProfileName);
        Names.AddUnique(ProfileName);
        if (bAssignAll)
        {
            for (UPhysicsConstraintTemplate* Constraint : PhysicsAsset->ConstraintSetup)
            {
                if (!Constraint || Constraint->ContainsConstraintProfile(ProfileName))
                {
                    AssignmentCount += Constraint ? 1 : 0;
                    continue;
                }
                Constraint->Modify();
                Constraint->AddConstraintProfile(ProfileName);
                Constraint->PostEditChange();
                ++AssignmentCount;
            }
        }
    }
    PhysicsAsset->PostEditChange();
    const bool bSaved = AIStudioSaveAssetPackage(PhysicsAsset);
    Root->SetBoolField(TEXT("ok"), bSaved);
    Root->SetStringField(TEXT("status"), bSaved ? (bCreated ? TEXT("profile_created_and_saved") : TEXT("profile_already_exists")) : TEXT("profile_save_failed"));
    Root->SetStringField(TEXT("profile_name"), ProfileName.ToString());
    Root->SetStringField(TEXT("profile_type"), bPhysicalAnimation ? TEXT("physical_animation") : TEXT("constraint"));
    Root->SetBoolField(TEXT("assign_all"), bAssignAll);
    Root->SetNumberField(TEXT("assignment_count"), AssignmentCount);
#else
    Root->SetStringField(TEXT("status"), TEXT("editor_only"));
#endif
    return AIStudioJsonString(Root);
}

FString UAIStudioBridgeLibrary::RemovePhysicsProfile(
    const FString& PhysicsAssetPath,
    FName ProfileName,
    const FString& ProfileType)
{
    const TSharedRef<FJsonObject> Root = MakeShared<FJsonObject>();
    Root->SetStringField(TEXT("capability"), TEXT("remove_physics_profile"));
    Root->SetStringField(TEXT("python_call"), TEXT("unreal.AIStudioBridgeLibrary.remove_physics_profile(physics_asset_path, profile_name, profile_type)"));
    Root->SetBoolField(TEXT("ok"), false);
#if WITH_EDITOR
    UPhysicsAsset* PhysicsAsset = Cast<UPhysicsAsset>(AIStudioLoadAssetObject(PhysicsAssetPath));
    const FString NormalizedType = ProfileType.TrimStartAndEnd().ToLower();
    const bool bPhysicalAnimation = NormalizedType == TEXT("physical_animation") || NormalizedType == TEXT("physical");
    const bool bConstraint = NormalizedType == TEXT("constraint") || NormalizedType == TEXT("constraints");
    if (!PhysicsAsset || ProfileName.IsNone() || (!bPhysicalAnimation && !bConstraint))
    {
        Root->SetStringField(
            TEXT("status"),
            !PhysicsAsset ? TEXT("physics_asset_not_found") : ProfileName.IsNone() ? TEXT("profile_name_required") : TEXT("invalid_profile_type"));
        return AIStudioJsonString(Root);
    }
    const FScopedTransaction Transaction(NSLOCTEXT("AIStudioBridge", "RemovePhysicsProfile", "AIStudioBridge Remove Physics Profile"));
    PhysicsAsset->Modify();
    int32 RemovedAssignments = 0;
    int32 RemovedNames = 0;
    if (bPhysicalAnimation)
    {
        TArray<FName>& Names = const_cast<TArray<FName>&>(PhysicsAsset->GetPhysicalAnimationProfileNames());
        RemovedNames = Names.Remove(ProfileName);
        for (USkeletalBodySetup* Body : PhysicsAsset->SkeletalBodySetups)
        {
            if (!Body || !Body->FindPhysicalAnimationProfile(ProfileName))
            {
                continue;
            }
            Body->Modify();
            Body->RemovePhysicalAnimationProfile(ProfileName);
            Body->PostEditChange();
            ++RemovedAssignments;
        }
    }
    else
    {
        TArray<FName>& Names = const_cast<TArray<FName>&>(PhysicsAsset->GetConstraintProfileNames());
        RemovedNames = Names.Remove(ProfileName);
        for (UPhysicsConstraintTemplate* Constraint : PhysicsAsset->ConstraintSetup)
        {
            if (!Constraint || !Constraint->ContainsConstraintProfile(ProfileName))
            {
                continue;
            }
            Constraint->Modify();
            Constraint->RemoveConstraintProfile(ProfileName);
            Constraint->PostEditChange();
            ++RemovedAssignments;
        }
    }
    if (RemovedNames > 0 || RemovedAssignments > 0)
    {
        PhysicsAsset->PostEditChange();
    }
    const bool bSaved = (RemovedNames > 0 || RemovedAssignments > 0) && AIStudioSaveAssetPackage(PhysicsAsset);
    Root->SetBoolField(TEXT("ok"), bSaved);
    Root->SetStringField(TEXT("status"), bSaved ? TEXT("profile_removed_and_saved") : TEXT("profile_not_found"));
    Root->SetStringField(TEXT("profile_name"), ProfileName.ToString());
    Root->SetStringField(TEXT("profile_type"), bPhysicalAnimation ? TEXT("physical_animation") : TEXT("constraint"));
    Root->SetNumberField(TEXT("removed_assignments"), RemovedAssignments);
#else
    Root->SetStringField(TEXT("status"), TEXT("editor_only"));
#endif
    return AIStudioJsonString(Root);
}

