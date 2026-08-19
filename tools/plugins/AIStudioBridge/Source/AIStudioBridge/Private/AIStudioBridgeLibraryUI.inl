static UClass* AIStudioResolveWidgetClass(const FString& ClassName)
{
    if (ClassName.Equals(TEXT("CanvasPanel"), ESearchCase::IgnoreCase)) return UCanvasPanel::StaticClass();
    if (ClassName.Equals(TEXT("VerticalBox"), ESearchCase::IgnoreCase)) return UVerticalBox::StaticClass();
    if (ClassName.Equals(TEXT("HorizontalBox"), ESearchCase::IgnoreCase)) return UHorizontalBox::StaticClass();
    if (ClassName.Equals(TEXT("Overlay"), ESearchCase::IgnoreCase)) return UOverlay::StaticClass();
    if (ClassName.Equals(TEXT("Border"), ESearchCase::IgnoreCase)) return UBorder::StaticClass();
    if (ClassName.Equals(TEXT("Button"), ESearchCase::IgnoreCase)) return UButton::StaticClass();
    if (ClassName.Equals(TEXT("SizeBox"), ESearchCase::IgnoreCase)) return USizeBox::StaticClass();
    if (ClassName.Equals(TEXT("TextBlock"), ESearchCase::IgnoreCase)) return UTextBlock::StaticClass();
    if (ClassName.Equals(TEXT("Image"), ESearchCase::IgnoreCase)) return UImage::StaticClass();
    if (ClassName.Equals(TEXT("ProgressBar"), ESearchCase::IgnoreCase)) return UProgressBar::StaticClass();
    if (ClassName.Equals(TEXT("Spacer"), ESearchCase::IgnoreCase)) return USpacer::StaticClass();
    return nullptr;
}

FString UAIStudioBridgeLibrary::AuthorWidgetBlueprint(
    const FString& WidgetBlueprintPath,
    FName RootName,
    FName TextName,
    const FString& Text,
    bool bSave)
{
    const TSharedRef<FJsonObject> Root = MakeShared<FJsonObject>();
    Root->SetBoolField(TEXT("ok"), false);
    Root->SetStringField(
        TEXT("python_call"),
        TEXT("unreal.AIStudioBridgeLibrary.author_widget_blueprint(widget_blueprint_path, root_name, text_name, text, save)"));
#if WITH_EDITOR
    UWidgetBlueprint* Blueprint = Cast<UWidgetBlueprint>(AIStudioLoadAssetObject(WidgetBlueprintPath));
    if (!Blueprint || !Blueprint->WidgetTree)
    {
        Root->SetStringField(TEXT("error"), TEXT("Widget Blueprint or design-time WidgetTree was not found."));
        Root->SetStringField(TEXT("asset_path"), WidgetBlueprintPath);
        return AIStudioJsonString(Root);
    }

    const FScopedTransaction Transaction(NSLOCTEXT(
        "AIStudioBridge",
        "AuthorWidgetBlueprint",
        "Tech Connector: Author Widget Blueprint"));
    Blueprint->Modify();
    Blueprint->WidgetTree->Modify();

    if (Blueprint->WidgetTree->RootWidget)
    {
        Blueprint->WidgetTree->RemoveWidget(Blueprint->WidgetTree->RootWidget);
        Blueprint->WidgetTree->RootWidget = nullptr;
    }
    const FName ResolvedRootName = RootName.IsNone() ? FName(TEXT("RootCanvas")) : RootName;
    const FName ResolvedTextName = TextName.IsNone() ? FName(TEXT("TitleText")) : TextName;
    UCanvasPanel* Canvas = Blueprint->WidgetTree->ConstructWidget<UCanvasPanel>(
        UCanvasPanel::StaticClass(),
        ResolvedRootName);
    UTextBlock* TextBlock = Blueprint->WidgetTree->ConstructWidget<UTextBlock>(
        UTextBlock::StaticClass(),
        ResolvedTextName);
    if (!Canvas || !TextBlock)
    {
        Root->SetStringField(TEXT("error"), TEXT("Could not construct the requested UMG widgets."));
        return AIStudioJsonString(Root);
    }
    TextBlock->SetText(FText::FromString(Text));
    UCanvasPanelSlot* Slot = Canvas->AddChildToCanvas(TextBlock);
    if (!Slot)
    {
        Root->SetStringField(TEXT("error"), TEXT("Could not attach the TextBlock to the CanvasPanel."));
        return AIStudioJsonString(Root);
    }
    Slot->SetAutoSize(true);
    Slot->SetPosition(FVector2D(64.0, 64.0));
    Blueprint->WidgetTree->RootWidget = Canvas;

    FBlueprintEditorUtils::MarkBlueprintAsStructurallyModified(Blueprint);
    FKismetEditorUtilities::CompileBlueprint(Blueprint);
    const bool bSaved = !bSave || AIStudioSaveAssetPackage(Blueprint);
    TArray<UWidget*> Widgets;
    Blueprint->WidgetTree->GetAllWidgets(Widgets);
    const bool bCompiled = Blueprint->Status != BS_Error;
    const bool bReadback = Blueprint->WidgetTree->RootWidget == Canvas
        && Blueprint->WidgetTree->FindWidget(ResolvedTextName) == TextBlock
        && TextBlock->GetText().ToString() == Text;

    Root->SetStringField(TEXT("asset_path"), WidgetBlueprintPath);
    Root->SetStringField(TEXT("root_name"), ResolvedRootName.ToString());
    Root->SetStringField(TEXT("root_class"), Canvas->GetClass()->GetPathName());
    Root->SetStringField(TEXT("text_name"), ResolvedTextName.ToString());
    Root->SetStringField(TEXT("text_class"), TextBlock->GetClass()->GetPathName());
    Root->SetStringField(TEXT("text"), TextBlock->GetText().ToString());
    Root->SetNumberField(TEXT("widget_count"), Widgets.Num());
    Root->SetBoolField(TEXT("compiled"), bCompiled);
    Root->SetBoolField(TEXT("saved"), bSaved);
    Root->SetBoolField(TEXT("readback"), bReadback);
    Root->SetBoolField(TEXT("ok"), bCompiled && bSaved && bReadback && Widgets.Num() == 2);
#else
    Root->SetStringField(TEXT("error"), TEXT("Tech Connector UMG authoring is editor-only."));
#endif
    return AIStudioJsonString(Root);
}

FString UAIStudioBridgeLibrary::AuthorWidgetBlueprintFromJson(
    const FString& WidgetBlueprintPath,
    const FString& WidgetSpecJson,
    bool bSave)
{
    const TSharedRef<FJsonObject> Root = MakeShared<FJsonObject>();
    Root->SetBoolField(TEXT("ok"), false);
    Root->SetStringField(
        TEXT("python_call"),
        TEXT("unreal.AIStudioBridgeLibrary.author_widget_blueprint_from_json(widget_blueprint_path, widget_spec_json, save)"));
#if WITH_EDITOR
    UWidgetBlueprint* Blueprint = Cast<UWidgetBlueprint>(AIStudioLoadAssetObject(WidgetBlueprintPath));
    if (!Blueprint || !Blueprint->WidgetTree)
    {
        Root->SetStringField(TEXT("error"), TEXT("Widget Blueprint or design-time WidgetTree was not found."));
        return AIStudioJsonString(Root);
    }
    TSharedPtr<FJsonObject> Specification;
    const TSharedRef<TJsonReader<>> Reader = TJsonReaderFactory<>::Create(WidgetSpecJson);
    if (!FJsonSerializer::Deserialize(Reader, Specification) || !Specification.IsValid())
    {
        Root->SetStringField(TEXT("error"), TEXT("Widget specification is not valid JSON."));
        return AIStudioJsonString(Root);
    }
    const TArray<TSharedPtr<FJsonValue>>* WidgetSpecs = nullptr;
    if (!Specification->TryGetArrayField(TEXT("widgets"), WidgetSpecs) || !WidgetSpecs || WidgetSpecs->IsEmpty())
    {
        Root->SetStringField(TEXT("error"), TEXT("Widget specification requires a non-empty widgets array."));
        return AIStudioJsonString(Root);
    }

    TSet<FString> ValidatedIds;
    TArray<TSharedPtr<FJsonObject>> Prepared;
    int32 RootCount = 0;
    for (const TSharedPtr<FJsonValue>& Value : *WidgetSpecs)
    {
        const TSharedPtr<FJsonObject> Row = Value.IsValid() ? Value->AsObject() : nullptr;
        if (!Row.IsValid())
        {
            Root->SetStringField(TEXT("error"), TEXT("Every widget specification must be an object."));
            return AIStudioJsonString(Root);
        }
        FString Id;
        FString ClassName;
        if (!Row->TryGetStringField(TEXT("id"), Id) || Id.TrimStartAndEnd().IsEmpty()
            || !Row->TryGetStringField(TEXT("class"), ClassName)
            || !AIStudioResolveWidgetClass(ClassName))
        {
            Root->SetStringField(TEXT("error"), TEXT("Each widget requires a unique id and supported class."));
            return AIStudioJsonString(Root);
        }
        Id = Id.TrimStartAndEnd();
        if (ValidatedIds.Contains(Id))
        {
            Root->SetStringField(TEXT("error"), TEXT("Widget ids must be unique."));
            Root->SetStringField(TEXT("duplicate_id"), Id);
            return AIStudioJsonString(Root);
        }
        FString ParentId;
        Row->TryGetStringField(TEXT("parent"), ParentId);
        if (ParentId.IsEmpty())
        {
            ++RootCount;
        }
        else if (!ValidatedIds.Contains(ParentId))
        {
            Root->SetStringField(TEXT("error"), TEXT("Widget parents must appear before their children."));
            Root->SetStringField(TEXT("widget_id"), Id);
            Root->SetStringField(TEXT("parent_id"), ParentId);
            return AIStudioJsonString(Root);
        }
        ValidatedIds.Add(Id);
        Prepared.Add(Row);
    }
    if (RootCount != 1)
    {
        Root->SetStringField(TEXT("error"), TEXT("Widget specification must contain exactly one root widget."));
        Root->SetNumberField(TEXT("root_count"), RootCount);
        return AIStudioJsonString(Root);
    }

    const FScopedTransaction Transaction(NSLOCTEXT(
        "AIStudioBridge",
        "AuthorWidgetBlueprintFromJson",
        "Tech Connector: Author Widget Blueprint From Specification"));
    Blueprint->Modify();
    Blueprint->WidgetTree->Modify();
    if (Blueprint->WidgetTree->RootWidget)
    {
        Blueprint->WidgetTree->RemoveWidget(Blueprint->WidgetTree->RootWidget);
        Blueprint->WidgetTree->RootWidget = nullptr;
    }

    TMap<FString, UWidget*> Authored;
    TArray<TSharedPtr<FJsonValue>> ReadbackRows;
    for (const TSharedPtr<FJsonObject>& Row : Prepared)
    {
        FString Id;
        FString ClassName;
        FString ParentId;
        FString WidgetName;
        Row->TryGetStringField(TEXT("id"), Id);
        Row->TryGetStringField(TEXT("class"), ClassName);
        Row->TryGetStringField(TEXT("parent"), ParentId);
        if (!Row->TryGetStringField(TEXT("name"), WidgetName) || WidgetName.IsEmpty())
        {
            WidgetName = Id;
        }
        UClass* WidgetClass = AIStudioResolveWidgetClass(ClassName);
        UWidget* Widget = Blueprint->WidgetTree->ConstructWidget<UWidget>(WidgetClass, FName(*WidgetName));
        if (!Widget)
        {
            Root->SetStringField(TEXT("error"), TEXT("Could not construct a requested widget."));
            Root->SetStringField(TEXT("widget_id"), Id);
            return AIStudioJsonString(Root);
        }
        if (UTextBlock* TextBlock = Cast<UTextBlock>(Widget))
        {
            FString Text;
            if (Row->TryGetStringField(TEXT("text"), Text))
            {
                TextBlock->SetText(FText::FromString(Text));
            }
        }
        if (UProgressBar* ProgressBar = Cast<UProgressBar>(Widget))
        {
            double Percent = 0.0;
            if (Row->TryGetNumberField(TEXT("percent"), Percent))
            {
                ProgressBar->SetPercent(FMath::Clamp(static_cast<float>(Percent), 0.0f, 1.0f));
            }
        }
        if (ParentId.IsEmpty())
        {
            Blueprint->WidgetTree->RootWidget = Widget;
        }
        else
        {
            UPanelWidget* Parent = Cast<UPanelWidget>(Authored.FindRef(ParentId));
            if (!Parent)
            {
                Root->SetStringField(TEXT("error"), TEXT("Requested widget parent is not a panel widget."));
                Root->SetStringField(TEXT("widget_id"), Id);
                Root->SetStringField(TEXT("parent_id"), ParentId);
                return AIStudioJsonString(Root);
            }
            UPanelSlot* Slot = Parent->AddChild(Widget);
            if (!Slot)
            {
                Root->SetStringField(TEXT("error"), TEXT("Could not attach widget to requested parent."));
                return AIStudioJsonString(Root);
            }
            if (UCanvasPanelSlot* CanvasSlot = Cast<UCanvasPanelSlot>(Slot))
            {
                const TArray<TSharedPtr<FJsonValue>>* Position = nullptr;
                if (Row->TryGetArrayField(TEXT("position"), Position) && Position && Position->Num() == 2)
                {
                    CanvasSlot->SetPosition(FVector2D(
                        static_cast<float>((*Position)[0]->AsNumber()),
                        static_cast<float>((*Position)[1]->AsNumber())));
                }
                const TArray<TSharedPtr<FJsonValue>>* Size = nullptr;
                if (Row->TryGetArrayField(TEXT("size"), Size) && Size && Size->Num() == 2)
                {
                    CanvasSlot->SetSize(FVector2D(
                        static_cast<float>((*Size)[0]->AsNumber()),
                        static_cast<float>((*Size)[1]->AsNumber())));
                }
                bool bAutoSize = false;
                if (Row->TryGetBoolField(TEXT("auto_size"), bAutoSize))
                {
                    CanvasSlot->SetAutoSize(bAutoSize);
                }
            }
        }
        Authored.Add(Id, Widget);
        const TSharedRef<FJsonObject> Readback = MakeShared<FJsonObject>();
        Readback->SetStringField(TEXT("id"), Id);
        Readback->SetStringField(TEXT("name"), Widget->GetName());
        Readback->SetStringField(TEXT("class"), Widget->GetClass()->GetPathName());
        Readback->SetStringField(TEXT("parent"), ParentId);
        if (const UTextBlock* TextBlock = Cast<UTextBlock>(Widget))
        {
            Readback->SetStringField(TEXT("text"), TextBlock->GetText().ToString());
        }
        if (const UProgressBar* ProgressBar = Cast<UProgressBar>(Widget))
        {
            Readback->SetNumberField(TEXT("percent"), ProgressBar->GetPercent());
        }
        if (const UCanvasPanelSlot* CanvasSlot = Cast<UCanvasPanelSlot>(Widget->Slot))
        {
            const FVector2D Position = CanvasSlot->GetPosition();
            const FVector2D Size = CanvasSlot->GetSize();
            Readback->SetArrayField(TEXT("position"), {
                MakeShared<FJsonValueNumber>(Position.X),
                MakeShared<FJsonValueNumber>(Position.Y),
            });
            Readback->SetArrayField(TEXT("size"), {
                MakeShared<FJsonValueNumber>(Size.X),
                MakeShared<FJsonValueNumber>(Size.Y),
            });
            Readback->SetBoolField(TEXT("auto_size"), CanvasSlot->GetAutoSize());
        }
        ReadbackRows.Add(MakeShared<FJsonValueObject>(Readback));
    }

    FBlueprintEditorUtils::MarkBlueprintAsStructurallyModified(Blueprint);
    FKismetEditorUtilities::CompileBlueprint(Blueprint);
    const bool bCompiled = Blueprint->Status != BS_Error;
    const bool bSaved = !bSave || AIStudioSaveAssetPackage(Blueprint);
    TArray<UWidget*> Widgets;
    Blueprint->WidgetTree->GetAllWidgets(Widgets);
    const bool bReadback = Widgets.Num() == Prepared.Num()
        && Blueprint->WidgetTree->RootWidget != nullptr;
    Root->SetStringField(TEXT("asset_path"), WidgetBlueprintPath);
    Root->SetStringField(TEXT("root_name"), Blueprint->WidgetTree->RootWidget
        ? Blueprint->WidgetTree->RootWidget->GetName()
        : TEXT(""));
    Root->SetNumberField(TEXT("widget_count"), Widgets.Num());
    Root->SetArrayField(TEXT("widgets"), ReadbackRows);
    Root->SetBoolField(TEXT("compiled"), bCompiled);
    Root->SetBoolField(TEXT("saved"), bSaved);
    Root->SetBoolField(TEXT("readback"), bReadback);
    Root->SetBoolField(TEXT("ok"), bCompiled && bSaved && bReadback);
#else
    Root->SetStringField(TEXT("error"), TEXT("Tech Connector UMG authoring is editor-only."));
#endif
    return AIStudioJsonString(Root);
}

FString UAIStudioBridgeLibrary::AuthorBehaviorTreeBaseline(
    const FString& BehaviorTreePath,
    const FString& BlackboardPath,
    float WaitSeconds,
    bool bSave)
{
#if WITH_EDITOR
    const TSharedRef<FJsonObject> Root = MakeShared<FJsonObject>();
    Root->SetBoolField(TEXT("ok"), false);
    Root->SetStringField(
        TEXT("python_call"),
        TEXT("unreal.AIStudioBridgeLibrary.author_behavior_tree_baseline(behavior_tree_path, blackboard_path, wait_seconds, save)"));
    return AuthorBehaviorTreeWaitGraph(
        BehaviorTreePath,
        BlackboardPath,
        TEXT("selector"),
        TArray<float>{FMath::Max(0.0f, WaitSeconds)},
        bSave);
#else
    const TSharedRef<FJsonObject> Root = MakeShared<FJsonObject>();
    Root->SetBoolField(TEXT("ok"), false);
    Root->SetStringField(
        TEXT("python_call"),
        TEXT("unreal.AIStudioBridgeLibrary.author_behavior_tree_baseline(behavior_tree_path, blackboard_path, wait_seconds, save)"));
    Root->SetStringField(TEXT("error"), TEXT("Tech Connector Behavior Tree authoring is editor-only."));
    return AIStudioJsonString(Root);
#endif
}

FString UAIStudioBridgeLibrary::AuthorBehaviorTreeWaitGraph(
    const FString& BehaviorTreePath,
    const FString& BlackboardPath,
    const FString& CompositeType,
    const TArray<float>& WaitSeconds,
    bool bSave)
{
    const TSharedRef<FJsonObject> Root = MakeShared<FJsonObject>();
    Root->SetBoolField(TEXT("ok"), false);
    Root->SetStringField(
        TEXT("python_call"),
        TEXT("unreal.AIStudioBridgeLibrary.author_behavior_tree_wait_graph(behavior_tree_path, blackboard_path, composite_type, wait_seconds, save)"));
#if WITH_EDITOR
    const bool bSelector = CompositeType.Equals(TEXT("selector"), ESearchCase::IgnoreCase);
    const bool bSequence = CompositeType.Equals(TEXT("sequence"), ESearchCase::IgnoreCase);
    if (!bSelector && !bSequence)
    {
        Root->SetStringField(TEXT("error"), TEXT("Composite type must be selector or sequence."));
        return AIStudioJsonString(Root);
    }
    if (WaitSeconds.IsEmpty())
    {
        Root->SetStringField(TEXT("error"), TEXT("Behavior Tree wait graph requires at least one Wait task."));
        return AIStudioJsonString(Root);
    }
    UBehaviorTree* Tree = Cast<UBehaviorTree>(AIStudioLoadAssetObject(BehaviorTreePath));
    UBlackboardData* Blackboard = BlackboardPath.IsEmpty()
        ? nullptr
        : Cast<UBlackboardData>(AIStudioLoadAssetObject(BlackboardPath));
    if (!Tree)
    {
        Root->SetStringField(TEXT("error"), TEXT("Behavior Tree asset was not found."));
        Root->SetStringField(TEXT("asset_path"), BehaviorTreePath);
        return AIStudioJsonString(Root);
    }
    if (!BlackboardPath.IsEmpty() && !Blackboard)
    {
        Root->SetStringField(TEXT("error"), TEXT("Requested Blackboard Data asset was not found."));
        Root->SetStringField(TEXT("blackboard_path"), BlackboardPath);
        return AIStudioJsonString(Root);
    }
    UBehaviorTreeGraph* Graph = Cast<UBehaviorTreeGraph>(Tree->BTGraph);
    if (!Graph)
    {
        Tree->Modify();
        Graph = NewObject<UBehaviorTreeGraph>(Tree, NAME_None, RF_Transactional);
        Graph->Schema = UEdGraphSchema_BehaviorTree::StaticClass();
        Tree->BTGraph = Graph;
        Graph->OnCreated();
        Graph->Initialize();
        const UEdGraphSchema* InitialSchema = Graph->GetSchema();
        if (InitialSchema && Graph->Nodes.IsEmpty())
        {
            InitialSchema->CreateDefaultNodesForGraph(*Graph);
        }
    }
    UBehaviorTreeGraphNode_Root* RootNode = nullptr;
    for (UEdGraphNode* Node : Graph->Nodes)
    {
        if (UBehaviorTreeGraphNode_Root* Candidate = Cast<UBehaviorTreeGraphNode_Root>(Node))
        {
            RootNode = Candidate;
            break;
        }
    }
    if (!RootNode)
    {
        Root->SetStringField(TEXT("error"), TEXT("Behavior Tree editor graph root node was not found."));
        return AIStudioJsonString(Root);
    }

    const FScopedTransaction Transaction(NSLOCTEXT(
        "AIStudioBridge",
        "AuthorBehaviorTreeWaitGraph",
        "Tech Connector: Author Behavior Tree Wait Graph"));
    Tree->Modify();
    Graph->Modify();
    RootNode->Modify();
    RootNode->BreakAllNodeLinks();
    TArray<UEdGraphNode*> ExistingNodes = Graph->Nodes;
    for (UEdGraphNode* Node : ExistingNodes)
    {
        if (Node && Node != RootNode)
        {
            Graph->RemoveNode(Node, true, true);
        }
    }

    Tree->BlackboardAsset = Blackboard;
    RootNode->BlackboardAsset = Blackboard;
    RootNode->NodePosX = 0;
    RootNode->NodePosY = 0;

    UBehaviorTreeGraphNode_Composite* CompositeNode = NewObject<UBehaviorTreeGraphNode_Composite>(
        Graph,
        NAME_None,
        RF_Transactional);
    CompositeNode->NodeInstance = bSelector
        ? static_cast<UBTNode*>(NewObject<UBTComposite_Selector>(Tree, NAME_None, RF_Transactional))
        : static_cast<UBTNode*>(NewObject<UBTComposite_Sequence>(Tree, NAME_None, RF_Transactional));
    CompositeNode->CreateNewGuid();
    CompositeNode->NodePosX = 0;
    CompositeNode->NodePosY = 180;
    CompositeNode->UpdateNodeClassData();
    Graph->AddNode(CompositeNode, true, false);
    CompositeNode->PostPlacedNewNode();
    CompositeNode->AllocateDefaultPins();

    const UEdGraphSchema* Schema = Graph->GetSchema();
    const bool bRootConnected = Schema
        && RootNode->GetOutputPin()
        && CompositeNode->GetInputPin()
        && Schema->TryCreateConnection(RootNode->GetOutputPin(), CompositeNode->GetInputPin());
    bool bTasksConnected = true;
    TArray<TSharedPtr<FJsonValue>> WaitRows;
    for (int32 Index = 0; Index < WaitSeconds.Num(); ++Index)
    {
        const float ResolvedWait = FMath::Max(0.0f, WaitSeconds[Index]);
        UBehaviorTreeGraphNode_Task* WaitNode = NewObject<UBehaviorTreeGraphNode_Task>(
            Graph,
            NAME_None,
            RF_Transactional);
        UBTTask_Wait* WaitTask = NewObject<UBTTask_Wait>(Tree, NAME_None, RF_Transactional);
        if (FStructProperty* WaitProperty = FindFProperty<FStructProperty>(
            UBTTask_Wait::StaticClass(),
            TEXT("WaitTime")))
        {
            if (FValueOrBBKey_Float* WaitValue = WaitProperty->ContainerPtrToValuePtr<FValueOrBBKey_Float>(WaitTask))
            {
                *WaitValue = FValueOrBBKey_Float(ResolvedWait);
            }
        }
        WaitNode->NodeInstance = WaitTask;
        WaitNode->CreateNewGuid();
        WaitNode->NodePosX = Index * 280;
        WaitNode->NodePosY = 360;
        WaitNode->UpdateNodeClassData();
        Graph->AddNode(WaitNode, true, false);
        WaitNode->PostPlacedNewNode();
        WaitNode->AllocateDefaultPins();
        const bool bConnected = Schema
            && CompositeNode->GetOutputPin()
            && WaitNode->GetInputPin()
            && Schema->TryCreateConnection(CompositeNode->GetOutputPin(), WaitNode->GetInputPin());
        bTasksConnected = bTasksConnected && bConnected;
        const TSharedRef<FJsonObject> WaitRow = MakeShared<FJsonObject>();
        WaitRow->SetNumberField(TEXT("index"), Index);
        WaitRow->SetNumberField(TEXT("wait_seconds"), ResolvedWait);
        WaitRow->SetBoolField(TEXT("connected"), bConnected);
        WaitRows.Add(MakeShared<FJsonValueObject>(WaitRow));
    }
    if (!bRootConnected || !bTasksConnected)
    {
        Root->SetStringField(TEXT("error"), TEXT("Behavior Tree schema rejected a wait-graph connection."));
        Root->SetBoolField(TEXT("root_connected"), bRootConnected);
        Root->SetBoolField(TEXT("tasks_connected"), bTasksConnected);
        return AIStudioJsonString(Root);
    }

    Graph->UpdateAsset(UBehaviorTreeGraph::RebuildGraph);
    Graph->OnSave();
    const bool bSaved = !bSave || AIStudioSaveAssetPackage(Tree);
    const int32 RuntimeChildren = Tree->RootNode ? Tree->RootNode->GetChildrenNum() : 0;
    const bool bRuntimeComposite = Tree->RootNode && (
        (bSelector && Tree->RootNode->IsA<UBTComposite_Selector>())
        || (bSequence && Tree->RootNode->IsA<UBTComposite_Sequence>()));
    bool bRuntimeWaits = RuntimeChildren == WaitSeconds.Num();
    for (int32 Index = 0; Index < RuntimeChildren && bRuntimeWaits; ++Index)
    {
        bRuntimeWaits = Tree->RootNode->GetChildNode(Index)
            && Tree->RootNode->GetChildNode(Index)->IsA<UBTTask_Wait>();
    }

    Root->SetStringField(TEXT("asset_path"), BehaviorTreePath);
    Root->SetStringField(TEXT("blackboard_path"), BlackboardPath);
    Root->SetStringField(TEXT("composite_type"), bSelector ? TEXT("selector") : TEXT("sequence"));
    Root->SetArrayField(TEXT("wait_tasks"), WaitRows);
    Root->SetNumberField(TEXT("editor_node_count"), Graph->Nodes.Num());
    Root->SetNumberField(TEXT("runtime_child_count"), RuntimeChildren);
    Root->SetBoolField(TEXT("root_connected"), bRootConnected);
    Root->SetBoolField(TEXT("tasks_connected"), bTasksConnected);
    Root->SetBoolField(TEXT("runtime_composite"), bRuntimeComposite);
    Root->SetBoolField(TEXT("runtime_wait_tasks"), bRuntimeWaits);
    Root->SetBoolField(TEXT("blackboard_bound"), Tree->BlackboardAsset == Blackboard);
    Root->SetBoolField(TEXT("saved"), bSaved);
    Root->SetBoolField(
        TEXT("ok"),
        bSaved
        && Graph->Nodes.Num() == WaitSeconds.Num() + 2
        && bRuntimeComposite
        && bRuntimeWaits);
#else
    Root->SetStringField(TEXT("error"), TEXT("Tech Connector Behavior Tree authoring is editor-only."));
#endif
    return AIStudioJsonString(Root);
}

FString UAIStudioBridgeLibrary::AuthorBehaviorTreeTaskGraph(
    const FString& BehaviorTreePath,
    const FString& BlackboardPath,
    const FString& CompositeType,
    const FString& TaskSpecJson,
    bool bSave)
{
    const TSharedRef<FJsonObject> Root = MakeShared<FJsonObject>();
    Root->SetBoolField(TEXT("ok"), false);
    Root->SetStringField(
        TEXT("python_call"),
        TEXT("unreal.AIStudioBridgeLibrary.author_behavior_tree_task_graph(behavior_tree_path, blackboard_path, composite_type, task_spec_json, save)"));
#if WITH_EDITOR
    const bool bSelector = CompositeType.Equals(TEXT("selector"), ESearchCase::IgnoreCase);
    const bool bSequence = CompositeType.Equals(TEXT("sequence"), ESearchCase::IgnoreCase);
    if (!bSelector && !bSequence)
    {
        Root->SetStringField(TEXT("error"), TEXT("Composite type must be selector or sequence."));
        return AIStudioJsonString(Root);
    }

    UBehaviorTree* Tree = Cast<UBehaviorTree>(AIStudioLoadAssetObject(BehaviorTreePath));
    UBlackboardData* Blackboard = BlackboardPath.IsEmpty()
        ? nullptr
        : Cast<UBlackboardData>(AIStudioLoadAssetObject(BlackboardPath));
    if (!Tree)
    {
        Root->SetStringField(TEXT("error"), TEXT("Behavior Tree asset was not found."));
        Root->SetStringField(TEXT("asset_path"), BehaviorTreePath);
        return AIStudioJsonString(Root);
    }
    if (!Blackboard)
    {
        Root->SetStringField(TEXT("error"), TEXT("Mixed task graphs require a valid Blackboard Data asset."));
        Root->SetStringField(TEXT("blackboard_path"), BlackboardPath);
        return AIStudioJsonString(Root);
    }

    struct FAIStudioBehaviorTaskSpec
    {
        FString Type;
        FName BlackboardKey;
        float Value = 0.0f;
    };
    TSharedPtr<FJsonObject> Specification;
    const TSharedRef<TJsonReader<>> Reader = TJsonReaderFactory<>::Create(TaskSpecJson);
    if (!FJsonSerializer::Deserialize(Reader, Specification) || !Specification.IsValid())
    {
        Root->SetStringField(TEXT("error"), TEXT("Task specification is not valid JSON."));
        return AIStudioJsonString(Root);
    }
    const TArray<TSharedPtr<FJsonValue>>* TaskValues = nullptr;
    if (!Specification->TryGetArrayField(TEXT("tasks"), TaskValues) || !TaskValues || TaskValues->IsEmpty())
    {
        Root->SetStringField(TEXT("error"), TEXT("Task specification requires a non-empty tasks array."));
        return AIStudioJsonString(Root);
    }

    TArray<FAIStudioBehaviorTaskSpec> TaskSpecs;
    for (int32 Index = 0; Index < TaskValues->Num(); ++Index)
    {
        const TSharedPtr<FJsonObject> Row = (*TaskValues)[Index].IsValid()
            ? (*TaskValues)[Index]->AsObject()
            : nullptr;
        if (!Row.IsValid())
        {
            Root->SetStringField(TEXT("error"), FString::Printf(TEXT("Task %d must be an object."), Index));
            return AIStudioJsonString(Root);
        }
        FAIStudioBehaviorTaskSpec TaskSpec;
        Row->TryGetStringField(TEXT("type"), TaskSpec.Type);
        TaskSpec.Type.TrimStartAndEndInline();
        TaskSpec.Type.ToLowerInline();
        if (TaskSpec.Type == TEXT("wait"))
        {
            double Seconds = 0.0;
            if (!Row->TryGetNumberField(TEXT("seconds"), Seconds))
            {
                Row->TryGetNumberField(TEXT("wait_seconds"), Seconds);
            }
            TaskSpec.Value = FMath::Max(0.0f, static_cast<float>(Seconds));
        }
        else if (TaskSpec.Type == TEXT("move_to") || TaskSpec.Type == TEXT("moveto"))
        {
            TaskSpec.Type = TEXT("move_to");
            FString KeyName;
            Row->TryGetStringField(TEXT("blackboard_key"), KeyName);
            KeyName.TrimStartAndEndInline();
            if (KeyName.IsEmpty())
            {
                Root->SetStringField(TEXT("error"), FString::Printf(TEXT("Move To task %d requires blackboard_key."), Index));
                return AIStudioJsonString(Root);
            }
            TaskSpec.BlackboardKey = FName(*KeyName);
            if (Blackboard->GetKeyID(TaskSpec.BlackboardKey) == FBlackboard::InvalidKey)
            {
                Root->SetStringField(
                    TEXT("error"),
                    FString::Printf(TEXT("Blackboard key was not found for Move To task %d: %s"), Index, *KeyName));
                return AIStudioJsonString(Root);
            }
            double Radius = 50.0;
            Row->TryGetNumberField(TEXT("acceptable_radius"), Radius);
            TaskSpec.Value = FMath::Max(0.0f, static_cast<float>(Radius));
        }
        else
        {
            Root->SetStringField(
                TEXT("error"),
                FString::Printf(TEXT("Unsupported task type at index %d: %s"), Index, *TaskSpec.Type));
            return AIStudioJsonString(Root);
        }
        TaskSpecs.Add(TaskSpec);
    }

    UBehaviorTreeGraph* Graph = Cast<UBehaviorTreeGraph>(Tree->BTGraph);
    if (!Graph)
    {
        Tree->Modify();
        Graph = NewObject<UBehaviorTreeGraph>(Tree, NAME_None, RF_Transactional);
        Graph->Schema = UEdGraphSchema_BehaviorTree::StaticClass();
        Tree->BTGraph = Graph;
        Graph->OnCreated();
        Graph->Initialize();
        const UEdGraphSchema* InitialSchema = Graph->GetSchema();
        if (InitialSchema && Graph->Nodes.IsEmpty())
        {
            InitialSchema->CreateDefaultNodesForGraph(*Graph);
        }
    }
    UBehaviorTreeGraphNode_Root* RootNode = nullptr;
    for (UEdGraphNode* Node : Graph->Nodes)
    {
        if (UBehaviorTreeGraphNode_Root* Candidate = Cast<UBehaviorTreeGraphNode_Root>(Node))
        {
            RootNode = Candidate;
            break;
        }
    }
    if (!RootNode)
    {
        Root->SetStringField(TEXT("error"), TEXT("Behavior Tree editor graph root node was not found."));
        return AIStudioJsonString(Root);
    }

    const FScopedTransaction Transaction(NSLOCTEXT(
        "AIStudioBridge",
        "AuthorBehaviorTreeTaskGraph",
        "Tech Connector: Author Mixed Behavior Tree Task Graph"));
    Tree->Modify();
    Graph->Modify();
    RootNode->Modify();
    RootNode->BreakAllNodeLinks();
    const TArray<UEdGraphNode*> ExistingNodes = Graph->Nodes;
    for (UEdGraphNode* Node : ExistingNodes)
    {
        if (Node && Node != RootNode)
        {
            Graph->RemoveNode(Node, true, true);
        }
    }
    Tree->BlackboardAsset = Blackboard;
    RootNode->BlackboardAsset = Blackboard;
    RootNode->NodePosX = 0;
    RootNode->NodePosY = 0;

    UBehaviorTreeGraphNode_Composite* CompositeNode = NewObject<UBehaviorTreeGraphNode_Composite>(
        Graph, NAME_None, RF_Transactional);
    CompositeNode->NodeInstance = bSelector
        ? static_cast<UBTNode*>(NewObject<UBTComposite_Selector>(Tree, NAME_None, RF_Transactional))
        : static_cast<UBTNode*>(NewObject<UBTComposite_Sequence>(Tree, NAME_None, RF_Transactional));
    CompositeNode->CreateNewGuid();
    CompositeNode->NodePosX = 0;
    CompositeNode->NodePosY = 180;
    CompositeNode->UpdateNodeClassData();
    Graph->AddNode(CompositeNode, true, false);
    CompositeNode->PostPlacedNewNode();
    CompositeNode->AllocateDefaultPins();

    const UEdGraphSchema* Schema = Graph->GetSchema();
    const bool bRootConnected = Schema
        && RootNode->GetOutputPin()
        && CompositeNode->GetInputPin()
        && Schema->TryCreateConnection(RootNode->GetOutputPin(), CompositeNode->GetInputPin());
    bool bTasksConnected = true;
    TArray<TSharedPtr<FJsonValue>> TaskRows;
    for (int32 Index = 0; Index < TaskSpecs.Num(); ++Index)
    {
        const FAIStudioBehaviorTaskSpec& TaskSpec = TaskSpecs[Index];
        UBehaviorTreeGraphNode_Task* TaskNode = NewObject<UBehaviorTreeGraphNode_Task>(
            Graph, NAME_None, RF_Transactional);
        UBTTaskNode* RuntimeTask = nullptr;
        if (TaskSpec.Type == TEXT("wait"))
        {
            UBTTask_Wait* WaitTask = NewObject<UBTTask_Wait>(Tree, NAME_None, RF_Transactional);
            if (FStructProperty* WaitProperty = FindFProperty<FStructProperty>(
                UBTTask_Wait::StaticClass(), TEXT("WaitTime")))
            {
                if (FValueOrBBKey_Float* WaitValue = WaitProperty->ContainerPtrToValuePtr<FValueOrBBKey_Float>(WaitTask))
                {
                    *WaitValue = FValueOrBBKey_Float(TaskSpec.Value);
                }
            }
            RuntimeTask = WaitTask;
        }
        else
        {
            UBTTask_MoveTo* MoveTask = NewObject<UBTTask_MoveTo>(Tree, NAME_None, RF_Transactional);
            if (FStructProperty* RadiusProperty = FindFProperty<FStructProperty>(
                UBTTask_MoveTo::StaticClass(), TEXT("AcceptableRadius")))
            {
                if (FValueOrBBKey_Float* RadiusValue = RadiusProperty->ContainerPtrToValuePtr<FValueOrBBKey_Float>(MoveTask))
                {
                    *RadiusValue = FValueOrBBKey_Float(TaskSpec.Value);
                }
            }
            if (FStructProperty* KeyProperty = FindFProperty<FStructProperty>(
                UBTTask_BlackboardBase::StaticClass(), TEXT("BlackboardKey")))
            {
                if (FBlackboardKeySelector* Selector = KeyProperty->ContainerPtrToValuePtr<FBlackboardKeySelector>(MoveTask))
                {
                    Selector->SelectedKeyName = TaskSpec.BlackboardKey;
                    Selector->ResolveSelectedKey(*Blackboard);
                }
            }
            RuntimeTask = MoveTask;
        }
        TaskNode->NodeInstance = RuntimeTask;
        TaskNode->CreateNewGuid();
        TaskNode->NodePosX = Index * 300;
        TaskNode->NodePosY = 360;
        TaskNode->UpdateNodeClassData();
        Graph->AddNode(TaskNode, true, false);
        TaskNode->PostPlacedNewNode();
        TaskNode->AllocateDefaultPins();
        const bool bConnected = Schema
            && CompositeNode->GetOutputPin()
            && TaskNode->GetInputPin()
            && Schema->TryCreateConnection(CompositeNode->GetOutputPin(), TaskNode->GetInputPin());
        bTasksConnected = bTasksConnected && bConnected;

        const TSharedRef<FJsonObject> TaskRow = MakeShared<FJsonObject>();
        TaskRow->SetNumberField(TEXT("index"), Index);
        TaskRow->SetStringField(TEXT("type"), TaskSpec.Type);
        TaskRow->SetStringField(TEXT("class"), RuntimeTask ? RuntimeTask->GetClass()->GetName() : TEXT(""));
        TaskRow->SetBoolField(TEXT("connected"), bConnected);
        if (TaskSpec.Type == TEXT("wait"))
        {
            TaskRow->SetNumberField(TEXT("wait_seconds"), TaskSpec.Value);
        }
        else
        {
            TaskRow->SetStringField(TEXT("blackboard_key"), TaskSpec.BlackboardKey.ToString());
            TaskRow->SetNumberField(TEXT("acceptable_radius"), TaskSpec.Value);
        }
        TaskRows.Add(MakeShared<FJsonValueObject>(TaskRow));
    }
    if (!bRootConnected || !bTasksConnected)
    {
        Root->SetStringField(TEXT("error"), TEXT("Behavior Tree schema rejected a task-graph connection."));
        Root->SetBoolField(TEXT("root_connected"), bRootConnected);
        Root->SetBoolField(TEXT("tasks_connected"), bTasksConnected);
        return AIStudioJsonString(Root);
    }

    Graph->UpdateAsset(UBehaviorTreeGraph::RebuildGraph);
    Graph->OnSave();
    const bool bSaved = !bSave || AIStudioSaveAssetPackage(Tree);
    const int32 RuntimeChildren = Tree->RootNode ? Tree->RootNode->GetChildrenNum() : 0;
    const bool bRuntimeComposite = Tree->RootNode && (
        (bSelector && Tree->RootNode->IsA<UBTComposite_Selector>())
        || (bSequence && Tree->RootNode->IsA<UBTComposite_Sequence>()));
    bool bRuntimeTasks = RuntimeChildren == TaskSpecs.Num();
    TArray<TSharedPtr<FJsonValue>> RuntimeRows;
    for (int32 Index = 0; Index < RuntimeChildren; ++Index)
    {
        UBTNode* RuntimeNode = Tree->RootNode->GetChildNode(Index);
        const bool bHasSpec = TaskSpecs.IsValidIndex(Index);
        const bool bExpected = bHasSpec && RuntimeNode && (
            (TaskSpecs[Index].Type == TEXT("wait") && RuntimeNode->IsA<UBTTask_Wait>())
            || (TaskSpecs[Index].Type == TEXT("move_to") && RuntimeNode->IsA<UBTTask_MoveTo>()));
        bRuntimeTasks = bRuntimeTasks && bExpected;
        const TSharedRef<FJsonObject> RuntimeRow = MakeShared<FJsonObject>();
        RuntimeRow->SetNumberField(TEXT("index"), Index);
        RuntimeRow->SetStringField(TEXT("class"), RuntimeNode ? RuntimeNode->GetClass()->GetName() : TEXT(""));
        RuntimeRow->SetBoolField(TEXT("matches_spec"), bExpected);
        if (bHasSpec)
        {
            if (const UBTTask_MoveTo* MoveTask = Cast<UBTTask_MoveTo>(RuntimeNode))
            {
                RuntimeRow->SetStringField(TEXT("blackboard_key"), MoveTask->GetSelectedBlackboardKey().ToString());
                bRuntimeTasks = bRuntimeTasks
                    && MoveTask->GetSelectedBlackboardKey() == TaskSpecs[Index].BlackboardKey;
            }
        }
        RuntimeRows.Add(MakeShared<FJsonValueObject>(RuntimeRow));
    }

    Root->SetStringField(TEXT("asset_path"), BehaviorTreePath);
    Root->SetStringField(TEXT("blackboard_path"), BlackboardPath);
    Root->SetStringField(TEXT("composite_type"), bSelector ? TEXT("selector") : TEXT("sequence"));
    Root->SetArrayField(TEXT("tasks"), TaskRows);
    Root->SetArrayField(TEXT("runtime_tasks"), RuntimeRows);
    Root->SetNumberField(TEXT("editor_node_count"), Graph->Nodes.Num());
    Root->SetNumberField(TEXT("runtime_child_count"), RuntimeChildren);
    Root->SetBoolField(TEXT("root_connected"), bRootConnected);
    Root->SetBoolField(TEXT("tasks_connected"), bTasksConnected);
    Root->SetBoolField(TEXT("runtime_composite"), bRuntimeComposite);
    Root->SetBoolField(TEXT("runtime_tasks_match"), bRuntimeTasks);
    Root->SetBoolField(TEXT("blackboard_bound"), Tree->BlackboardAsset == Blackboard);
    Root->SetBoolField(TEXT("saved"), bSaved);
    Root->SetBoolField(
        TEXT("ok"),
        bSaved
        && Graph->Nodes.Num() == TaskSpecs.Num() + 2
        && bRuntimeComposite
        && bRuntimeTasks
        && Tree->BlackboardAsset == Blackboard);
#else
    Root->SetStringField(TEXT("error"), TEXT("Tech Connector Behavior Tree authoring is editor-only."));
#endif
    return AIStudioJsonString(Root);
}
