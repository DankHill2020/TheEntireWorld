// Audio-domain authoring implementation included by AIStudioBridgeLibrary.cpp.

FString UAIStudioBridgeLibrary::CreateSoundCueFromWave(
    const FString& SoundCuePath,
    const FString& SoundWavePath,
    const FString& ProcessorSpecJson,
    bool bLooping,
    float VolumeMultiplier,
    float PitchMultiplier,
    bool bOverwrite,
    bool bSave)
{
    const TSharedRef<FJsonObject> Root = MakeShared<FJsonObject>();
    Root->SetBoolField(TEXT("ok"), false);
    Root->SetStringField(
        TEXT("python_call"),
        TEXT("unreal.AIStudioBridgeLibrary.create_sound_cue_from_wave(sound_cue_path, sound_wave_path, processor_spec_json, looping, volume_multiplier, pitch_multiplier, overwrite, save)"));
#if WITH_EDITOR
    if (!SoundCuePath.StartsWith(TEXT("/Game/")))
    {
        Root->SetStringField(TEXT("error"), TEXT("Sound Cue path must be below /Game."));
        return AIStudioJsonString(Root);
    }
    if (VolumeMultiplier < 0.0f || PitchMultiplier < 0.0f)
    {
        Root->SetStringField(TEXT("error"), TEXT("Volume and pitch multipliers cannot be negative."));
        return AIStudioJsonString(Root);
    }
    USoundWave* SoundWave = Cast<USoundWave>(AIStudioLoadAssetObject(SoundWavePath));
    if (!SoundWave)
    {
        Root->SetStringField(TEXT("error"), TEXT("Sound Wave asset was not found."));
        Root->SetStringField(TEXT("sound_wave_path"), SoundWavePath);
        return AIStudioJsonString(Root);
    }

    struct FAIStudioSoundProcessorSpec
    {
        FString ClassName;
        UClass* NodeClass = nullptr;
        TSharedPtr<FJsonObject> Properties;
    };
    TArray<FAIStudioSoundProcessorSpec> ProcessorSpecs;
    if (!ProcessorSpecJson.IsEmpty())
    {
        TSharedPtr<FJsonObject> Specification;
        const TSharedRef<TJsonReader<>> Reader = TJsonReaderFactory<>::Create(ProcessorSpecJson);
        if (!FJsonSerializer::Deserialize(Reader, Specification) || !Specification.IsValid())
        {
            Root->SetStringField(TEXT("error"), TEXT("Sound Cue processor specification is not valid JSON."));
            return AIStudioJsonString(Root);
        }
        const TArray<TSharedPtr<FJsonValue>>* ProcessorValues = nullptr;
        if (Specification->TryGetArrayField(TEXT("processors"), ProcessorValues) && ProcessorValues)
        {
            for (int32 Index = 0; Index < ProcessorValues->Num(); ++Index)
            {
                const TSharedPtr<FJsonObject> Row = (*ProcessorValues)[Index].IsValid()
                    ? (*ProcessorValues)[Index]->AsObject()
                    : nullptr;
                FString ClassName;
                if (!Row.IsValid() || !Row->TryGetStringField(TEXT("class"), ClassName))
                {
                    Root->SetStringField(TEXT("error"), FString::Printf(TEXT("Processor %d requires class."), Index));
                    return AIStudioJsonString(Root);
                }
                ClassName.TrimStartAndEndInline();
                if (!ClassName.StartsWith(TEXT("SoundNode")))
                {
                    Root->SetStringField(TEXT("error"), TEXT("Processor classes must start with SoundNode."));
                    return AIStudioJsonString(Root);
                }
                const FString ClassPath = FString::Printf(TEXT("/Script/Engine.%s"), *ClassName);
                UClass* NodeClass = LoadClass<USoundNode>(nullptr, *ClassPath);
                if (!NodeClass || !NodeClass->IsChildOf(USoundNode::StaticClass()) || NodeClass->HasAnyClassFlags(CLASS_Abstract))
                {
                    Root->SetStringField(TEXT("error"), TEXT("Unsupported Sound Cue processor class: ") + ClassName);
                    return AIStudioJsonString(Root);
                }
                const TSharedPtr<FJsonObject>* Properties = nullptr;
                Row->TryGetObjectField(TEXT("properties"), Properties);
                FAIStudioSoundProcessorSpec ProcessorSpec;
                ProcessorSpec.ClassName = ClassName;
                ProcessorSpec.NodeClass = NodeClass;
                ProcessorSpec.Properties = Properties ? *Properties : MakeShared<FJsonObject>();
                ProcessorSpecs.Add(ProcessorSpec);
            }
        }
    }

    FString PackagePath;
    FString AssetName;
    if (!SoundCuePath.Split(TEXT("/"), &PackagePath, &AssetName, ESearchCase::CaseSensitive, ESearchDir::FromEnd)
        || PackagePath.IsEmpty()
        || AssetName.IsEmpty())
    {
        Root->SetStringField(TEXT("error"), TEXT("Sound Cue path is invalid."));
        return AIStudioJsonString(Root);
    }
    UObject* Existing = AIStudioLoadAssetObject(SoundCuePath);
    if (Existing && !bOverwrite)
    {
        Root->SetStringField(TEXT("error"), TEXT("Sound Cue already exists; enable overwrite to replace it."));
        Root->SetStringField(TEXT("asset_path"), SoundCuePath);
        return AIStudioJsonString(Root);
    }
    if (Existing && (!Existing->IsA<USoundCue>() || !ObjectTools::DeleteSingleObject(Existing, true)))
    {
        Root->SetStringField(TEXT("error"), TEXT("Existing asset could not be safely replaced."));
        Root->SetStringField(TEXT("asset_path"), SoundCuePath);
        return AIStudioJsonString(Root);
    }

    USoundCueFactoryNew* Factory = NewObject<USoundCueFactoryNew>();
    Factory->InitialSoundWaves.Add(SoundWave);
    IAssetTools& AssetTools = FAssetToolsModule::GetModule().Get();
    USoundCue* Cue = Cast<USoundCue>(AssetTools.CreateAsset(
        AssetName,
        PackagePath,
        USoundCue::StaticClass(),
        Factory));
    if (!Cue)
    {
        Root->SetStringField(TEXT("error"), TEXT("Unreal failed to create the Sound Cue."));
        return AIStudioJsonString(Root);
    }

    Cue->Modify();
    Cue->VolumeMultiplier = VolumeMultiplier;
    Cue->PitchMultiplier = PitchMultiplier;
    USoundNodeWavePlayer* WavePlayer = Cast<USoundNodeWavePlayer>(Cue->FirstNode);
    if (!WavePlayer)
    {
        ObjectTools::DeleteSingleObject(Cue, false);
        Root->SetStringField(TEXT("error"), TEXT("Sound Cue factory did not create a Wave Player root."));
        return AIStudioJsonString(Root);
    }
    WavePlayer->Modify();
    WavePlayer->bLooping = bLooping;
    WavePlayer->PostEditChange();
    USoundNode* CurrentRoot = WavePlayer;
    TArray<TSharedPtr<FJsonValue>> ProcessorRows;
    for (int32 Index = ProcessorSpecs.Num() - 1; Index >= 0; --Index)
    {
        const FAIStudioSoundProcessorSpec& ProcessorSpec = ProcessorSpecs[Index];
        USoundNode* Processor = Cue->ConstructSoundNode<USoundNode>(ProcessorSpec.NodeClass, false);
        if (!Processor || Processor->GetMaxChildNodes() == 0)
        {
            ObjectTools::DeleteSingleObject(Cue, false);
            Root->SetStringField(TEXT("error"), TEXT("Sound processor cannot accept a child: ") + ProcessorSpec.ClassName);
            return AIStudioJsonString(Root);
        }
        for (const TPair<FString, TSharedPtr<FJsonValue>>& Pair : ProcessorSpec.Properties->Values)
        {
            FProperty* Property = Processor->GetClass()->FindPropertyByName(FName(*Pair.Key));
            if (!Property || !Property->HasAnyPropertyFlags(CPF_Edit))
            {
                ObjectTools::DeleteSingleObject(Cue, false);
                Root->SetStringField(TEXT("error"), TEXT("Sound processor property is unavailable or not editable: ") + Pair.Key);
                return AIStudioJsonString(Root);
            }
            void* ValuePtr = Property->ContainerPtrToValuePtr<void>(Processor);
            if (FNumericProperty* NumericProperty = CastField<FNumericProperty>(Property))
            {
                const double Number = Pair.Value->AsNumber();
                if (NumericProperty->IsFloatingPoint())
                {
                    NumericProperty->SetFloatingPointPropertyValue(ValuePtr, Number);
                }
                else
                {
                    NumericProperty->SetIntPropertyValue(ValuePtr, static_cast<int64>(Number));
                }
            }
            else if (FBoolProperty* BoolProperty = CastField<FBoolProperty>(Property))
            {
                BoolProperty->SetPropertyValue(ValuePtr, Pair.Value->AsBool());
            }
            else if (FNameProperty* NameProperty = CastField<FNameProperty>(Property))
            {
                NameProperty->SetPropertyValue(ValuePtr, FName(*Pair.Value->AsString()));
            }
            else if (FStrProperty* StringProperty = CastField<FStrProperty>(Property))
            {
                StringProperty->SetPropertyValue(ValuePtr, Pair.Value->AsString());
            }
            else
            {
                ObjectTools::DeleteSingleObject(Cue, false);
                Root->SetStringField(TEXT("error"), TEXT("Unsupported Sound processor property type: ") + Pair.Key);
                return AIStudioJsonString(Root);
            }
        }
        Processor->CreateStartingConnectors();
        if (Processor->ChildNodes.Num() != 1)
        {
            ObjectTools::DeleteSingleObject(Cue, false);
            Root->SetStringField(
                TEXT("error"),
                FString::Printf(
                    TEXT("Sound processor '%s' is not unary (it created %d input slots); "
                         "create_from_wave supports ordered one-input processor chains only."),
                    *ProcessorSpec.ClassName,
                    Processor->ChildNodes.Num()));
            return AIStudioJsonString(Root);
        }
        TArray<USoundNode*> Children{CurrentRoot};
        Processor->SetChildNodes(Children);
        Processor->PostEditChange();
        CurrentRoot = Processor;

        const TSharedRef<FJsonObject> ProcessorRow = MakeShared<FJsonObject>();
        ProcessorRow->SetNumberField(TEXT("index"), Index);
        ProcessorRow->SetStringField(TEXT("class"), ProcessorSpec.ClassName);
        ProcessorRows.Insert(MakeShared<FJsonValueObject>(ProcessorRow), 0);
    }
    Cue->FirstNode = CurrentRoot;
    Cue->LinkGraphNodesFromSoundNodes();
    Cue->PostEditChange();

    const bool bSaved = !bSave || AIStudioSaveAssetPackage(Cue);
    TArray<USoundNode*> RuntimeNodes;
    Cue->RecursiveFindAllNodes(Cue->FirstNode, RuntimeNodes);
    const bool bWaveMatches = WavePlayer->GetSoundWave() == SoundWave;
    const bool bLoopingMatches = static_cast<bool>(WavePlayer->bLooping) == bLooping;
    const bool bGraphReady = Cue->GetGraph() != nullptr;

    Root->SetStringField(TEXT("asset_path"), SoundCuePath);
    Root->SetStringField(TEXT("sound_wave_path"), SoundWavePath);
    Root->SetStringField(TEXT("first_node_class"), WavePlayer->GetClass()->GetPathName());
    Root->SetStringField(TEXT("graph_root_class"), CurrentRoot->GetClass()->GetPathName());
    Root->SetArrayField(TEXT("processors"), ProcessorRows);
    Root->SetNumberField(TEXT("processor_count"), ProcessorSpecs.Num());
    Root->SetNumberField(TEXT("runtime_node_count"), RuntimeNodes.Num());
    Root->SetBoolField(TEXT("wave_matches"), bWaveMatches);
    Root->SetBoolField(TEXT("looping"), bLooping);
    Root->SetBoolField(TEXT("looping_matches"), bLoopingMatches);
    Root->SetNumberField(TEXT("volume_multiplier"), Cue->VolumeMultiplier);
    Root->SetNumberField(TEXT("pitch_multiplier"), Cue->PitchMultiplier);
    Root->SetBoolField(TEXT("graph_ready"), bGraphReady);
    Root->SetBoolField(TEXT("saved"), bSaved);
    Root->SetBoolField(
        TEXT("ok"),
        bSaved
        && bWaveMatches
        && bLoopingMatches
        && bGraphReady
        && RuntimeNodes.Num() == ProcessorSpecs.Num() + 1);
#else
    Root->SetStringField(TEXT("error"), TEXT("Tech Connector Sound Cue authoring is editor-only."));
#endif
    return AIStudioJsonString(Root);
}
