static void AIStudioAppendNiagaraErrors(
    const FNiagaraExternalEditContext& Context,
    const TSharedRef<FJsonObject>& Root)
{
    TArray<TSharedPtr<FJsonValue>> Errors;
    for (const FText& Error : Context.Errors)
    {
        Errors.Add(MakeShared<FJsonValueString>(Error.ToString()));
    }
    Root->SetArrayField(TEXT("errors"), Errors);
}

static bool AIStudioSetInstancedStructValue(
    FInstancedStruct& Value,
    const FString& ValueJson,
    FString& OutError)
{
    const UScriptStruct* Struct = Value.GetScriptStruct();
    void* Memory = Value.GetMutableMemory();
    if (!Struct || !Memory)
    {
        OutError = TEXT("Niagara value has no concrete script struct.");
        return false;
    }

    TSharedPtr<FJsonValue> Parsed;
    const TSharedRef<TJsonReader<>> Reader = TJsonReaderFactory<>::Create(ValueJson);
    if (!FJsonSerializer::Deserialize(Reader, Parsed) || !Parsed.IsValid())
    {
        Parsed = MakeShared<FJsonValueString>(ValueJson);
    }
    TSharedRef<FJsonObject> Object = MakeShared<FJsonObject>();
    if (Parsed->Type == EJson::Object)
    {
        Object = Parsed->AsObject().ToSharedRef();
    }
    else if (Parsed->Type == EJson::Array)
    {
        const TArray<TSharedPtr<FJsonValue>>& Values = Parsed->AsArray();
        const TCHAR* Names[] = {TEXT("X"), TEXT("Y"), TEXT("Z"), TEXT("W")};
        for (int32 Index = 0; Index < FMath::Min(Values.Num(), 4); ++Index)
        {
            Object->SetField(Names[Index], Values[Index]);
        }
        if (Struct == TBaseStructure<FLinearColor>::Get())
        {
            const TArray<TSharedPtr<FJsonValue>> Copy = Values;
            Object = MakeShared<FJsonObject>();
            const TCHAR* ColorNames[] = {TEXT("R"), TEXT("G"), TEXT("B"), TEXT("A")};
            for (int32 Index = 0; Index < FMath::Min(Copy.Num(), 4); ++Index)
            {
                Object->SetField(ColorNames[Index], Copy[Index]);
            }
        }
    }
    else
    {
        Object->SetField(TEXT("Value"), Parsed);
    }
    FText FailReason;
    const bool bConverted = FJsonObjectConverter::JsonObjectToUStruct(
        Object,
        Struct,
        Memory,
        0,
        0,
        false,
        &FailReason);
    OutError = FailReason.ToString();
    return bConverted;
}

static TSharedRef<FJsonObject> AIStudioInstancedStructValueJson(const FInstancedStruct& Value)
{
    const TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
    const UScriptStruct* Struct = Value.GetScriptStruct();
    const void* Memory = Value.GetMemory();
    Row->SetStringField(TEXT("type"), Struct ? Struct->GetPathName() : TEXT(""));
    if (!Struct || !Memory)
    {
        Row->SetObjectField(TEXT("value"), MakeShared<FJsonObject>());
        return Row;
    }
    FString Json;
    FJsonObjectConverter::UStructToJsonObjectString(Struct, Memory, Json, 0, 0);
    TSharedPtr<FJsonObject> Parsed = AIStudioParseJsonObject(Json);
    Row->SetObjectField(TEXT("value"), Parsed.IsValid() ? Parsed.ToSharedRef() : MakeShared<FJsonObject>());
    Row->SetStringField(TEXT("exported_json"), Json);
    return Row;
}

static bool AIStudioMergeJsonProperty(
    FString& PropertyValues,
    FName PropertyName,
    const FString& ValueJson,
    FString& OutError)
{
    TSharedPtr<FJsonObject> Object = AIStudioParseJsonObject(PropertyValues);
    if (!Object.IsValid())
    {
        OutError = TEXT("Niagara property data was not a JSON object.");
        return false;
    }
    TSharedPtr<FJsonValue> Parsed;
    const TSharedRef<TJsonReader<>> Reader = TJsonReaderFactory<>::Create(ValueJson);
    if (!FJsonSerializer::Deserialize(Reader, Parsed) || !Parsed.IsValid())
    {
        Parsed = MakeShared<FJsonValueString>(ValueJson);
    }
    Object->SetField(PropertyName.ToString(), Parsed);
    const TSharedRef<TJsonWriter<>> Writer = TJsonWriterFactory<>::Create(&PropertyValues);
    return FJsonSerializer::Serialize(Object.ToSharedRef(), Writer);
}

FString UAIStudioBridgeLibrary::ListNiagaraModuleInputs(const FString& SystemPath, FName EmitterName)
{
    const TSharedRef<FJsonObject> Root = MakeShared<FJsonObject>();
    Root->SetStringField(TEXT("capability"), TEXT("list_niagara_module_inputs"));
    Root->SetStringField(TEXT("python_call"), TEXT("unreal.AIStudioBridgeLibrary.list_niagara_module_inputs(system_path, emitter_name)"));
    Root->SetBoolField(TEXT("ok"), false);
#if WITH_EDITOR
    UNiagaraSystem* System = Cast<UNiagaraSystem>(AIStudioLoadAssetObject(SystemPath));
    if (!System)
    {
        Root->SetStringField(TEXT("status"), TEXT("system_not_found"));
        return AIStudioJsonString(Root);
    }
    FNiagaraExternalEditContext Context(System);
    FNiagaraExt_SystemSummary Summary;
    UNiagaraExternalEditUtilities::GetSystemSummary(System, Summary, Context);
    TArray<TSharedPtr<FJsonValue>> Emitters;
    for (const FNiagaraExt_EmitterSummary& Emitter : Summary.Emitters)
    {
        if (!EmitterName.IsNone() && Emitter.EmitterName != EmitterName)
        {
            continue;
        }
        FNiagaraExt_StackItemReference Ref(System, Emitter.EmitterName);
        FNiagaraExt_EmitterTopology Topology;
        TArray<FNiagaraExt_ModuleInputValues> Values;
        UNiagaraExternalEditUtilities::GetEmitterTopology(Ref, Topology, Context);
        UNiagaraExternalEditUtilities::GetEmitterInputValues(Ref, Values, Context);
        FString TopologyJson;
        FJsonObjectConverter::UStructToJsonObjectString(FNiagaraExt_EmitterTopology::StaticStruct(), &Topology, TopologyJson, 0, 0);
        TArray<TSharedPtr<FJsonValue>> InputValues;
        for (const FNiagaraExt_ModuleInputValues& Value : Values)
        {
            const TSharedRef<FJsonObject> ValueObject = MakeShared<FJsonObject>();
            ValueObject->SetStringField(TEXT("moduleName"), Value.ModuleName.ToString());
            TArray<TSharedPtr<FJsonValue>> Inputs;
            for (const FNiagaraExt_StackInputValueEntry& Input : Value.Inputs)
            {
                const TSharedRef<FJsonObject> InputObject = MakeShared<FJsonObject>();
                InputObject->SetStringField(TEXT("name"), Input.Name.ToString());
                InputObject->SetObjectField(TEXT("value"), AIStudioInstancedStructValueJson(Input.Value));
                Inputs.Add(MakeShared<FJsonValueObject>(InputObject));
            }
            ValueObject->SetArrayField(TEXT("inputs"), Inputs);
            InputValues.Add(MakeShared<FJsonValueObject>(ValueObject));
        }
        const TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
        Row->SetStringField(TEXT("emitter_name"), Emitter.EmitterName.ToString());
        Row->SetStringField(TEXT("topology_json"), TopologyJson);
        Row->SetArrayField(TEXT("input_values"), InputValues);
        Emitters.Add(MakeShared<FJsonValueObject>(Row));
    }
    AIStudioAppendNiagaraErrors(Context, Root);
    Root->SetArrayField(TEXT("emitters"), Emitters);
    Root->SetNumberField(TEXT("emitter_count"), Emitters.Num());
    Root->SetBoolField(TEXT("ok"), !Context.HasErrors() && Emitters.Num() > 0);
    Root->SetStringField(TEXT("status"), Context.HasErrors() ? TEXT("inspection_failed") : TEXT("inspected"));
#else
    Root->SetStringField(TEXT("status"), TEXT("editor_only"));
#endif
    return AIStudioJsonString(Root);
}

FString UAIStudioBridgeLibrary::SetNiagaraUserParameter(
    const FString& SystemPath,
    FName ParameterName,
    const FString& ValueJson,
    const FString& ValueType)
{
    const TSharedRef<FJsonObject> Root = MakeShared<FJsonObject>();
    Root->SetStringField(TEXT("capability"), TEXT("set_niagara_user_parameter"));
    Root->SetStringField(TEXT("python_call"), TEXT("unreal.AIStudioBridgeLibrary.set_niagara_user_parameter(system_path, parameter_name, value_json, value_type)"));
    Root->SetBoolField(TEXT("ok"), false);
#if WITH_EDITOR
    UNiagaraSystem* System = Cast<UNiagaraSystem>(AIStudioLoadAssetObject(SystemPath));
    if (!System)
    {
        Root->SetStringField(TEXT("status"), TEXT("system_not_found"));
        return AIStudioJsonString(Root);
    }
    const FString TypeKey = ValueType.ToLower();
    const FNiagaraTypeDefinition* Type = &FNiagaraTypeDefinition::GetFloatDef();
    if (TypeKey == TEXT("bool") || TypeKey == TEXT("boolean")) Type = &FNiagaraTypeDefinition::GetBoolDef();
    else if (TypeKey == TEXT("int") || TypeKey == TEXT("int32")) Type = &FNiagaraTypeDefinition::GetIntDef();
    else if (TypeKey == TEXT("vector") || TypeKey == TEXT("vec3")) Type = &FNiagaraTypeDefinition::GetVec3Def();
    else if (TypeKey == TEXT("position")) Type = &FNiagaraTypeDefinition::GetPositionDef();
    else if (TypeKey == TEXT("color") || TypeKey == TEXT("linearcolor")) Type = &FNiagaraTypeDefinition::GetColorDef();

    FNiagaraExt_UserVariable Variable;
    Variable.Name = FName(*FString::Printf(TEXT("User.%s"), *ParameterName.ToString().Replace(TEXT("User."), TEXT(""))));
    Variable.Type = *Type;
    Variable.DefaultValue.InitializeAs(Type->GetScriptStruct());
    FString Error;
    if (!AIStudioSetInstancedStructValue(Variable.DefaultValue, ValueJson, Error))
    {
        Root->SetStringField(TEXT("status"), TEXT("value_parse_failed"));
        Root->SetStringField(TEXT("error"), Error);
        return AIStudioJsonString(Root);
    }
    FNiagaraExternalEditContext Context(System);
    FNiagaraExt_Variable Existing;
    Existing.Name = Variable.Name;
    Existing.Type = Variable.Type;
    UNiagaraExternalEditUtilities::RemoveUserVariable(System, Existing, Context);
    Context.Errors.Reset();
    UNiagaraExternalEditUtilities::AddUserVariable(System, Variable, Context);
    FNiagaraExt_UserVariables ReadbackVariables;
    if (!Context.HasErrors())
    {
        UNiagaraExternalEditUtilities::GetUserVariables(System, ReadbackVariables, Context);
    }
    const FNiagaraExt_UserVariable* Readback = ReadbackVariables.UserVariables.FindByPredicate(
        [&Variable](const FNiagaraExt_UserVariable& Candidate)
        {
            return Candidate.Name == Variable.Name && Candidate.Type == Variable.Type;
        });
    const bool bSaved = !Context.HasErrors() && Readback && AIStudioSaveAssetPackage(System);
    AIStudioAppendNiagaraErrors(Context, Root);
    Root->SetBoolField(TEXT("ok"), bSaved);
    Root->SetStringField(TEXT("status"), bSaved ? TEXT("parameter_set_and_saved") : TEXT("parameter_set_failed"));
    Root->SetStringField(TEXT("parameter_name"), Variable.Name.ToString());
    Root->SetStringField(TEXT("value_type"), TypeKey);
    if (Readback)
    {
        Root->SetObjectField(TEXT("readback"), AIStudioInstancedStructValueJson(Readback->DefaultValue));
    }
#else
    Root->SetStringField(TEXT("status"), TEXT("editor_only"));
#endif
    return AIStudioJsonString(Root);
}

FString UAIStudioBridgeLibrary::SetNiagaraRendererProperty(
    const FString& SystemPath,
    FName EmitterName,
    int32 RendererIndex,
    FName PropertyName,
    const FString& ValueJson)
{
    const TSharedRef<FJsonObject> Root = MakeShared<FJsonObject>();
    Root->SetStringField(TEXT("capability"), TEXT("set_niagara_renderer_property"));
    Root->SetStringField(TEXT("python_call"), TEXT("unreal.AIStudioBridgeLibrary.set_niagara_renderer_property(system_path, emitter_name, renderer_index, property_name, value_json)"));
    Root->SetBoolField(TEXT("ok"), false);
#if WITH_EDITOR
    UNiagaraSystem* System = Cast<UNiagaraSystem>(AIStudioLoadAssetObject(SystemPath));
    FNiagaraExternalEditContext Context(System);
    FNiagaraExt_StackItemReference Ref(System, EmitterName);
    Ref.RendererIndex = RendererIndex;
    FNiagaraExt_RendererData Data;
    if (System) UNiagaraExternalEditUtilities::GetRendererData(Ref, Data, Context);
    FString Error;
    if (!Context.HasErrors() && AIStudioMergeJsonProperty(Data.PropertyValues, PropertyName, ValueJson, Error))
    {
        UNiagaraExternalEditUtilities::SetRendererData(Ref, Data, Context);
    }
    FNiagaraExt_RendererData Readback;
    if (!Context.HasErrors() && Error.IsEmpty())
    {
        UNiagaraExternalEditUtilities::GetRendererData(Ref, Readback, Context);
    }
    const TSharedPtr<FJsonObject> ReadbackObject = AIStudioParseJsonObject(Readback.PropertyValues);
    const bool bHasReadback = ReadbackObject.IsValid() && ReadbackObject->HasField(PropertyName.ToString());
    const bool bSaved = !Context.HasErrors() && Error.IsEmpty() && bHasReadback && AIStudioSaveAssetPackage(System);
    AIStudioAppendNiagaraErrors(Context, Root);
    Root->SetBoolField(TEXT("ok"), bSaved);
    Root->SetStringField(TEXT("status"), bSaved ? TEXT("renderer_property_set_and_saved") : TEXT("renderer_property_set_failed"));
    Root->SetStringField(TEXT("error"), Error);
    Root->SetStringField(TEXT("readback_json"), Readback.PropertyValues);
#else
    Root->SetStringField(TEXT("status"), TEXT("editor_only"));
#endif
    return AIStudioJsonString(Root);
}

FString UAIStudioBridgeLibrary::SetNiagaraModuleInput(
    const FString& SystemPath,
    FName EmitterName,
    FName ScriptName,
    FName ModuleName,
    FName InputName,
    const FString& ValueJson)
{
    const TSharedRef<FJsonObject> Root = MakeShared<FJsonObject>();
    Root->SetStringField(TEXT("capability"), TEXT("set_niagara_module_input"));
    Root->SetStringField(TEXT("python_call"), TEXT("unreal.AIStudioBridgeLibrary.set_niagara_module_input(system_path, emitter_name, script_name, module_name, input_name, value_json)"));
    Root->SetBoolField(TEXT("ok"), false);
#if WITH_EDITOR
    UNiagaraSystem* System = Cast<UNiagaraSystem>(AIStudioLoadAssetObject(SystemPath));
    FNiagaraExternalEditContext Context(System);
    FNiagaraExt_StackItemReference Ref(System, EmitterName, ScriptName, ModuleName);
    Ref.InputNameStack.Add(InputName);
    FNiagaraExt_StackInputTopology Topology;
    FNiagaraExt_StackInputValue Data;
    if (System)
    {
        UNiagaraExternalEditUtilities::GetStackInputTopology(Ref, Topology, Context);
        UNiagaraExternalEditUtilities::GetStackInputData(Ref, Data, Context);
    }
    FString Error;
    bool bSetRequested = false;
    if (!Topology.bIsEditable)
    {
        Error = TEXT("The requested Niagara stack input is not editable in the current stack state.");
    }
    else if (!Context.HasErrors() && AIStudioSetInstancedStructValue(Data, ValueJson, Error))
    {
        UNiagaraExternalEditUtilities::SetStackInputData(Ref, Data, Context);
        bSetRequested = true;
    }
    FNiagaraExt_StackInputValue Readback;
    if (bSetRequested && !Context.HasErrors())
    {
        UNiagaraExternalEditUtilities::GetStackInputData(Ref, Readback, Context);
    }
    const bool bHasReadback = Readback.GetScriptStruct() != nullptr && Readback.GetMemory() != nullptr;
    const bool bSaved = bSetRequested
        && bHasReadback
        && !Context.HasErrors()
        && Error.IsEmpty()
        && AIStudioSaveAssetPackage(System);
    AIStudioAppendNiagaraErrors(Context, Root);
    Root->SetBoolField(TEXT("ok"), bSaved);
    Root->SetStringField(TEXT("status"), bSaved ? TEXT("module_input_set_and_saved") : TEXT("module_input_set_failed"));
    Root->SetStringField(TEXT("error"), Error);
    Root->SetStringField(TEXT("input_name"), InputName.ToString());
    Root->SetObjectField(TEXT("readback"), AIStudioInstancedStructValueJson(Readback));
#else
    Root->SetStringField(TEXT("status"), TEXT("editor_only"));
#endif
    return AIStudioJsonString(Root);
}

FString UAIStudioBridgeLibrary::RemoveNiagaraEmitter(const FString& SystemPath, FName EmitterName)
{
    const TSharedRef<FJsonObject> Root = MakeShared<FJsonObject>();
    Root->SetStringField(TEXT("capability"), TEXT("remove_niagara_emitter"));
    Root->SetStringField(TEXT("python_call"), TEXT("unreal.AIStudioBridgeLibrary.remove_niagara_emitter(system_path, emitter_name)"));
    Root->SetBoolField(TEXT("ok"), false);
#if WITH_EDITOR
    UNiagaraSystem* System = Cast<UNiagaraSystem>(AIStudioLoadAssetObject(SystemPath));
    FNiagaraExternalEditContext Context(System);
    FNiagaraExt_StackItemReference Ref(System, EmitterName);
    if (System) UNiagaraExternalEditUtilities::RemoveEmitter(Ref, Context);
    FNiagaraExt_SystemSummary Readback;
    if (!Context.HasErrors())
    {
        UNiagaraExternalEditUtilities::GetSystemSummary(System, Readback, Context);
    }
    const bool bRemoved = !Readback.Emitters.ContainsByPredicate(
        [EmitterName](const FNiagaraExt_EmitterSummary& Emitter)
        {
            return Emitter.EmitterName == EmitterName;
        });
    const bool bSaved = !Context.HasErrors() && bRemoved && AIStudioSaveAssetPackage(System);
    AIStudioAppendNiagaraErrors(Context, Root);
    Root->SetBoolField(TEXT("ok"), bSaved);
    Root->SetStringField(TEXT("status"), bSaved ? TEXT("emitter_removed_and_saved") : TEXT("emitter_remove_failed"));
    Root->SetBoolField(TEXT("removed"), bRemoved);
    Root->SetNumberField(TEXT("emitter_count"), Readback.Emitters.Num());
#else
    Root->SetStringField(TEXT("status"), TEXT("editor_only"));
#endif
    return AIStudioJsonString(Root);
}

FString UAIStudioBridgeLibrary::SetNiagaraEmitterProperty(
    const FString& SystemPath,
    FName EmitterName,
    FName PropertyName,
    const FString& ValueJson)
{
    const TSharedRef<FJsonObject> Root = MakeShared<FJsonObject>();
    Root->SetStringField(TEXT("capability"), TEXT("set_niagara_emitter_property"));
    Root->SetStringField(TEXT("python_call"), TEXT("unreal.AIStudioBridgeLibrary.set_niagara_emitter_property(system_path, emitter_name, property_name, value_json)"));
    Root->SetBoolField(TEXT("ok"), false);
#if WITH_EDITOR
    UNiagaraSystem* System = Cast<UNiagaraSystem>(AIStudioLoadAssetObject(SystemPath));
    FNiagaraExternalEditContext Context(System);
    FNiagaraExt_StackItemReference Ref(System, EmitterName);
    FNiagaraExt_EmitterData Data;
    if (System) UNiagaraExternalEditUtilities::GetEmitterData(Ref, Data, Context);
    FString Error;
    if (!Context.HasErrors() && AIStudioMergeJsonProperty(Data.PropertyValues, PropertyName, ValueJson, Error))
    {
        UNiagaraExternalEditUtilities::SetEmitterData(Ref, Data, Context);
    }
    FNiagaraExt_EmitterData Readback;
    if (!Context.HasErrors() && Error.IsEmpty())
    {
        UNiagaraExternalEditUtilities::GetEmitterData(Ref, Readback, Context);
    }
    const TSharedPtr<FJsonObject> ReadbackObject = AIStudioParseJsonObject(Readback.PropertyValues);
    const bool bHasReadback = ReadbackObject.IsValid() && ReadbackObject->HasField(PropertyName.ToString());
    const bool bSaved = !Context.HasErrors() && Error.IsEmpty() && bHasReadback && AIStudioSaveAssetPackage(System);
    AIStudioAppendNiagaraErrors(Context, Root);
    Root->SetBoolField(TEXT("ok"), bSaved);
    Root->SetStringField(TEXT("status"), bSaved ? TEXT("emitter_property_set_and_saved") : TEXT("emitter_property_set_failed"));
    Root->SetStringField(TEXT("error"), Error);
    Root->SetStringField(TEXT("readback_json"), Readback.PropertyValues);
#else
    Root->SetStringField(TEXT("status"), TEXT("editor_only"));
#endif
    return AIStudioJsonString(Root);
}
